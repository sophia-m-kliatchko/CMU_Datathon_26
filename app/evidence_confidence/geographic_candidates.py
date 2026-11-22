"""Local adapter executing the shared geographic notebook's scalar expressions.

The original notebook is read, never modified. DataFrame left joins/projections
are represented by unique-key Python rows. Source F expressions and the actual
haversine helper are compiled from AST, not replaced by a new distance formula.
Only the full `near` relation is evaluated: no service prefilter or top-25 display.
This is not execution on Spark; unsupported source expressions fail explicitly.
"""
import ast
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import math
from pathlib import Path
import re

from .adapters import _bool


def _value(value):
    return value.value if isinstance(value, _Column) else value


class _Column:
    def __init__(self, value):self.value=value
    def _op(self, other, operation):
        other=_value(other)
        return _Column(None if self.value is None or other is None else operation(self.value,other))
    def __add__(self,other):return self._op(other,lambda a,b:a+b)
    __radd__=__add__
    def __sub__(self,other):return self._op(other,lambda a,b:a-b)
    def __rsub__(self,other):return _Column(other).__sub__(self)
    def __mul__(self,other):return self._op(other,lambda a,b:a*b)
    __rmul__=__mul__
    def __truediv__(self,other):return self._op(other,lambda a,b:a/b)
    def __rtruediv__(self,other):return _Column(other).__truediv__(self)
    def __eq__(self,other):return self._op(other,lambda a,b:a==b)
    def __gt__(self,other):return self._op(other,lambda a,b:a>b)
    def __ge__(self,other):return self._op(other,lambda a,b:a>=b)
    def __lt__(self,other):return self._op(other,lambda a,b:a<b)
    def __le__(self,other):return self._op(other,lambda a,b:a<=b)
    def __and__(self,other):
        other=_value(other)
        return _Column(False if self.value is False or other is False else None if self.value is None or other is None else bool(self.value and other))
    __rand__=__and__
    def __invert__(self):return _Column(None if self.value is None else not self.value)
    def __bool__(self):raise TypeError('Use explicit SQL true/null handling, not Python truthiness')
    def between(self,low,high):return (self>=low)&(self<=high)
    def isNotNull(self):return _Column(self.value is not None)
    def isNull(self):return _Column(self.value is None)


class _When(_Column):
    def __init__(self,condition,value):
        self.matched=_value(condition) is True
        super().__init__(_value(value) if self.matched else None)
    def when(self,condition,value):
        if not self.matched and _value(condition) is True:
            self.matched=True;self.value=_value(value)
        return self
    def otherwise(self,value):return _Column(self.value if self.matched else _value(value))


class _Functions:
    """Only the scalar Spark functions used by the inspected producer."""
    def __init__(self,row=None):self.row={} if row is None else row
    def col(self,name):
        if name not in self.row:raise ValueError(f'missing geographic input column {name}')
        return _Column(self.row[name])
    @staticmethod
    def lit(value):return _Column(value)
    @staticmethod
    def coalesce(*values):return _Column(next((_value(v) for v in values if _value(v) is not None),None))
    @staticmethod
    def when(condition,value):return _When(condition,value)
    @staticmethod
    def _math(function,value):return _Column(None if _value(value) is None else function(_value(value)))
    def sin(self,value):return self._math(math.sin,value)
    def cos(self,value):return self._math(math.cos,value)
    def sqrt(self,value):return self._math(math.sqrt,value)
    def asin(self,value):return self._math(math.asin,value)
    @staticmethod
    def pow(value,power):return _Column(value)._op(power,lambda a,b:a**b) if not isinstance(value,_Column) else value._op(power,lambda a,b:a**b)
    @staticmethod
    def least(*values):
        values=[_value(v) for v in values if _value(v) is not None]
        return _Column(min(values) if values else None)
    @staticmethod
    def greatest(*values):
        values=[_value(v) for v in values if _value(v) is not None]
        return _Column(max(values) if values else None)
    @staticmethod
    def round(value,scale):
        value=_value(value)
        return _Column(None if value is None else float(Decimal(str(value)).quantize(Decimal(1).scaleb(-scale),rounding=ROUND_HALF_UP)))


def _expression(node, filename):
    return compile(ast.Expression(node),str(filename),'eval')


def _number(value, field):
    if value in (None,''):return None
    if isinstance(value,bool):raise ValueError(f'{field} must be numeric')
    result=float(value)
    if not math.isfinite(result):raise ValueError(f'{field} must be finite')
    return result


NOTEBOOK_PATHS=('notebooks/07_pin_nearby_facilities.py','notebooks/common/pin_nearby_facilities.py')


def default_notebook(root):
    """Elliot's renamed 07 notebook if present (Elliot_New_Branch), else the legacy common/ copy."""
    for rel in NOTEBOOK_PATHS:
        if (Path(root)/rel).is_file():return Path(root)/rel
    raise ValueError('geographic producer notebook not found: '+', '.join(NOTEBOOK_PATHS))


LEGACY_FIELDS={'city':'city_clean','state':'state_clean','pincode':'pincode_clean',
               'latitude':'latitude_clean','longitude':'longitude_clean'}


def facility_view(record):
    """Explicit legacy projection: raw lat/lon never overwrite cleaned values."""
    row=dict(record)
    legacy='pincode_clean' in row
    mapping={}
    for current,old in LEGACY_FIELDS.items():
        if legacy:
            if old not in row:raise ValueError(f'legacy facilities missing {old}')
            row[current]=record[old];mapping[current]=old
        elif current not in row:raise ValueError(f'facilities missing {current}')
    for key in ('facility_id','name','coords_low_precision','coord_status'):
        if key not in row:raise ValueError(f'facilities missing {key}')
    if not isinstance(row['facility_id'],str) or not row['facility_id'].strip():raise ValueError('canonical facility_id required')
    row['latitude']=_number(row['latitude'],'latitude');row['longitude']=_number(row['longitude'],'longitude')
    row['coords_low_precision']=_bool(row['coords_low_precision'])
    return row,mapping


class GeographicProducer:
    def __init__(self, notebook_path, validation_path):
        self.path=Path(notebook_path);self.validation_path=Path(validation_path)
        source=self.path.read_text();self.source_sha256=hashlib.sha256(source.encode()).hexdigest()
        self.validation_sha256=hashlib.sha256(self.validation_path.read_bytes()).hexdigest()
        tree=ast.parse(source);nodes={}
        for node in ast.walk(tree):
            if isinstance(node,ast.Assign):
                for target in node.targets:
                    if isinstance(target,ast.Name):nodes.setdefault(target.id,node.value)
        self.constants={}
        for statement in tree.body:
            if isinstance(statement,ast.Assign):
                try:value=ast.literal_eval(statement.value)
                except (ValueError,TypeError):continue
                if len(statement.targets)==1:
                    target=statement.targets[0]
                    if isinstance(target,ast.Name):self.constants[target.id]=value
                    elif isinstance(target,ast.Tuple):self.constants.update((n.id,v) for n,v in zip(target.elts,value))
        for required in ('LAT_MIN','LAT_MAX','LON_MIN','LON_MAX','PIN_MATCH_KM','KM_PER_DEG_LAT'):
            if required not in self.constants:raise ValueError(f'geographic constant missing: {required}')
        htree=ast.parse(self.validation_path.read_text())
        fn=next(n for n in htree.body if isinstance(n,ast.FunctionDef) and n.name=='haversine_km_col')
        globals_={'F':_Functions()}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),str(self.validation_path),'exec'),globals_)
        self.haversine=globals_['haversine_km_col']
        self.selectors=[(name,_expression(nodes[name],self.path)) for name in ('in_box','d_pin','own_ok','pin_ok')]
        self.geo_columns=ast.literal_eval(nodes['GEO_COLS'])
        self.geo_ops=self._chain(nodes['geo'],{'withColumn'})
        self.near_ops=self._chain(nodes['near'],{'where','withColumn'})
        self.bounds=[(name,_expression(nodes[name],self.path)) for name in ('dlat','dlon')]
        # Later producer versions widen the prefilter box by the table-wide maximum
        # location uncertainty (`dlat += max_uncertainty / ...`). Apply those
        # augmented assignments in source order rather than silently ignoring them.
        self.bound_updates=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.AugAssign) and isinstance(node.target,ast.Name) and node.target.id in ('dlat','dlon'):
                if not isinstance(node.op,ast.Add):raise ValueError('unsupported geographic bound update')
                self.bound_updates.append((node.lineno,node.target.id,_expression(node.value,self.path)))
        self.bound_updates=[(name,code) for _,name,code in sorted(self.bound_updates,key=lambda x:x[0])]
        self.uses_max_uncertainty='max_uncertainty' in nodes
        if self.uses_max_uncertainty:
            # The Spark aggregate cannot be evaluated locally; accept only the exact
            # inspected definition, then compute that same aggregate over `ready`.
            expected="F.max(F.coalesce(F.col('location_uncertainty_km'), F.lit(0.0)))"
            if expected not in ast.unparse(nodes['max_uncertainty']):
                raise ValueError('unrecognized max_uncertainty definition; refusing to guess its semantics')
        elif self.bound_updates:
            raise ValueError('bound updates without a recognized max_uncertainty definition')
        # Filters that reference the prefilter box. Validation re-runs the source rule
        # without them to prove the box never drops a radius-eligible facility.
        self.box_dependent=[any(isinstance(n,ast.Name) and n.id in ('dlat','dlon') for n in ast.walk(code_node))
                            for code_node in self._chain_nodes(nodes['near'])]
        self.pin_expression=_expression(nodes['pin'],self.path)

    @staticmethod
    def _chain_nodes(node):
        found=[]
        while isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in ('where','withColumn'):
            found.append(node.args[-1]);node=node.func.value
        return list(reversed(found))

    def _chain(self,node,allowed):
        operations=[]
        while isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in allowed:
            name=node.func.attr
            if name=='withColumn':
                if not isinstance(node.args[0],ast.Constant):raise ValueError('unsupported dynamic geographic column')
                operations.append((name,node.args[0].value,_expression(node.args[1],self.path)))
            else:operations.append((name,None,_expression(node.args[0],self.path)))
            node=node.func.value
        if not operations:raise ValueError('geographic expression chain not found')
        return list(reversed(operations))

    def _environment(self,row):
        return {**self.constants,'F':_Functions(row),'haversine_km_col':self.haversine,'math':math,'max':max,'re':re}

    def build_ready(self,facilities,centroids):
        lookup={}
        for record in centroids:
            row=dict(record)
            for key in ('pincode','latitude','longitude','max_office_distance_km','centroid_quality','pin_ambiguous'):
                if key not in row:raise ValueError(f'PIN centroids missing {key}')
            pin=row['pincode']
            if not isinstance(pin,str) or not re.fullmatch(r'[1-9][0-9]{5}',pin):raise ValueError('invalid centroid PIN')
            if pin in lookup:raise ValueError('duplicate PIN centroids would multiply facilities')
            for key in ('latitude','longitude','max_office_distance_km'):row[key]=_number(row[key],key)
            if (row['latitude'] is None)!=(row['longitude'] is None):raise ValueError('half centroid coordinate pair')
            if row['latitude'] is not None and not (self.constants['LAT_MIN']<=row['latitude']<=self.constants['LAT_MAX'] and self.constants['LON_MIN']<=row['longitude']<=self.constants['LON_MAX']):raise ValueError('PIN centroid is outside the source India box')
            if row['max_office_distance_km'] is not None and row['max_office_distance_km']<0:raise ValueError('negative centroid spread')
            row['pin_ambiguous']=_bool(row['pin_ambiguous']);lookup[pin]=row
        ready=[];seen=set();mapping={}
        for record in facilities:
            row,aliases=facility_view(record);mapping.update(aliases)
            fid=row['facility_id']
            if fid in seen:raise ValueError('duplicate canonical facilities')
            seen.add(fid)
            centroid=lookup.get(row['pincode'])
            row.update(pin_lat=centroid['latitude'] if centroid else None,
                       pin_lon=centroid['longitude'] if centroid else None,
                       pin_spread_km=(centroid['max_office_distance_km'] if centroid['max_office_distance_km'] is not None else 0.) if centroid else None)
            env=self._environment(row)
            for name,code in self.selectors:env[name]=eval(code,{'__builtins__':{}},env)
            for _,name,code in self.geo_ops:row[name]=_value(eval(code,{'__builtins__':{}},env))
            output={key:row[key] for key in self.geo_columns if key in row}
            point=(output['geo_latitude'],output['geo_longitude'])
            if (point[0] is None)!=(point[1] is None):raise ValueError('derived half coordinate pair')
            if point[0] is not None and not (self.constants['LAT_MIN']<=point[0]<=self.constants['LAT_MAX'] and self.constants['LON_MIN']<=point[1]<=self.constants['LON_MAX']):raise ValueError('derived point outside source India box')
            if output['location_basis']=='facility_coordinates' and point!=(row['latitude'],row['longitude']):raise ValueError('facility point lost source identity')
            if output['location_basis']=='pin_centroid' and (centroid is None or point!=(centroid['latitude'],centroid['longitude'])):raise ValueError('fallback point not from the supplied PIN centroid')
            ready.append(output)
        return ready,lookup,{'facility_rows':len(ready),'unique_facility_ids':len(seen),
            'location_basis_counts':dict(Counter(str(r['location_basis']) for r in ready)),
            'geo_confidence_counts':dict(Counter(str(r['geo_confidence']) for r in ready)),
            'unsearchable_rows':sum(r['geo_latitude'] is None for r in ready),'legacy_projection':mapping,
            'source_sha256':self.source_sha256,'haversine_source_sha256':self.validation_sha256,
            'execution':'local evaluation of actual source AST scalar expressions; not Spark execution'}

    def candidates(self,ready,centroids,*,pin,radius_km,apply_prefilter=True):
        pin=eval(self.pin_expression,{'__builtins__':{}},{'raw':pin,'re':re})
        if not pin.isdigit() or len(pin)!=6 or pin[0]=='0':raise ValueError('invalid Indian PIN syntax')
        if pin not in centroids:raise ValueError('PIN missing from the supplied centroid directory')
        centroid=centroids[pin]
        if centroid['latitude'] is None:raise ValueError('PIN has no usable centroid coordinates')
        if isinstance(radius_km,bool) or not isinstance(radius_km,(float,int)) or not math.isfinite(radius_km) or radius_km<=0:raise ValueError('radius must be finite and positive')
        variables={'lat0':centroid['latitude'],'lon0':centroid['longitude'],'radius':radius_km}
        for name,code in self.bounds:variables[name]=eval(code,{'__builtins__':{}},{**self.constants,**variables,'math':math,'max':max})
        if self.uses_max_uncertainty:
            # Local equivalent of the inspected aggregate: max(coalesce(u, 0)) or 0.0.
            variables['max_uncertainty']=float(max((r.get('location_uncertainty_km') or 0. for r in ready),default=0.) or 0.)
        for name,code in self.bound_updates:
            variables[name]+=eval(code,{'__builtins__':{}},{**self.constants,**variables,'math':math,'max':max})
        result=[]
        for item in ready:
            row=dict(item);env={**self._environment(row),**variables}
            keep=True
            for (operation,name,code),boxed in zip(self.near_ops,self.box_dependent):
                if boxed and not apply_prefilter:continue
                value=eval(code,{'__builtins__':{}},env)
                if operation=='where' and _value(value) is not True:keep=False;break
                if operation=='withColumn':row[name]=_value(value)
            if keep:result.append(row)
        result.sort(key=lambda r:(r['distance_km'],r['facility_id']))
        return result,{'pin':pin,'radius_km':radius_km,'candidate_count':len(result),
            'prefilter_applied':apply_prefilter,'max_uncertainty_km':variables.get('max_uncertainty'),
            'radius_rule':('uncertainty_adjusted_distance_km <= radius_km'
                           if any(name=='uncertainty_adjusted_distance_km' for _,name,_ in self.near_ops)
                           else 'distance_km <= radius_km'),
            'service_prefiltered':False,'candidate_limit_applied':False,'retrieval_complete':True,
            'query_location':{k:centroid.get(k) for k in ('pincode','latitude','longitude','main_state','main_district',
                'centroid_quality','pin_ambiguous','max_office_distance_km','source_name','source_url','row_citation')},
            'limitations':['Distances are source-producer straight-line estimates from the query PIN centroid, not road distance.',
                'Facility uncertainty follows the existing source assumptions, not calibrated error bounds.',
                'Query PIN spread/ambiguity is preserved separately; it is not combined into invented distance bounds.']}


GEO_PASSTHROUGH=('facility_id','name','city','state','pincode','distance_km','location_basis',
                 'geo_confidence','location_uncertainty_km','coord_status','dq_flags')


def to_join_candidate(row):
    """Map one producer `near` row onto the join_geographic_candidates() contract.

    Fields are copied, never recomputed. The producer's own
    uncertainty_adjusted_distance_km = max(distance_km - location_uncertainty_km, 0)
    becomes distance_min_km. No upper bound is emitted by the producer, so none is
    invented: distance_max_km stays absent.
    """
    out={key:row.get(key) for key in GEO_PASSTHROUGH if key in row}
    for key in ('facility_id','distance_km','geo_confidence'):
        if key not in out:raise ValueError(f'geographic row missing {key}')
    if 'uncertainty_adjusted_distance_km' in row:
        out['distance_min_km']=row['uncertainty_adjusted_distance_km']
    return out
