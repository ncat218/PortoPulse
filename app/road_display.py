"""Separate coincident opposite road directions for display only."""
from collections import defaultdict

from pyproj import Transformer
from shapely import offset_curve, transform
from shapely.geometry import LineString, mapping


def separate_direction_geometries(features,metric_crs='EPSG:32629',offset_m=2.):
    groups=defaultdict(list);original={}
    for feature in features:
        eid=feature['properties']['edge_id'];geometry=feature['geometry']
        if geometry['type']!='LineString':
            raise ValueError('Expected directed LineString road geometry')
        coords=tuple(tuple(point) for point in geometry['coordinates'])
        original[eid]=geometry;groups[min(coords,coords[::-1])].append((eid,coords))
    forward=Transformer.from_crs('EPSG:4326',metric_crs,always_xy=True)
    inverse=Transformer.from_crs(metric_crs,'EPSG:4326',always_xy=True)
    separated={}
    for group in groups.values():
        directions={coords for _,coords in group}
        if len(directions)<2:
            continue
        for eid,coords in group:
            metric=transform(LineString(coords),forward.transform,interleaved=False)
            shifted=offset_curve(metric,offset_m)
            if shifted.geom_type=='LineString' and not shifted.is_empty:
                separated[eid]=mapping(transform(shifted,inverse.transform,interleaved=False))
    return {eid:separated.get(eid,geometry) for eid,geometry in original.items()}
