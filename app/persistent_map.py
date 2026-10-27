"""Persistent Leaflet map: acknowledge immutable roads, then send small overlays.

The browser requests the road payload again after an iframe reload. A Python
session acknowledgement alone must never leave a refreshed browser blank.
"""
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from ui_logic import STATUS_LABELS
from ui_logic import route_features

_component = components.declare_component('portopulse_map', path=str(Path(__file__).parent/'map_frontend'))
ROAD_FIELDS = ('edge_id', 'status', 'color', 'median_speed_kmh',
               'reference_speed_kmh', 'distinct_trips', 'distinct_taxis', 'distinct_dates')


def compact_roads(features):
    """Keep exact display coordinates and directional colors; omit repeated keys."""
    return [[feature['geometry']['coordinates'],
             *[feature['properties'][field] for field in ROAD_FIELDS]] for feature in features]


@st.cache_resource(max_entries=4)
def road_payload(dataset_id, _features):
    # The ID contains the export identity/hash and selected day/bucket.
    return compact_roads(_features)


def component_arguments(dataset_id, event, features, overlay, center, pick_mode):
    acknowledged = isinstance(event, dict) and event.get('dataset_id') == dataset_id
    return dict(dataset_id=dataset_id,
                roads=None if acknowledged else road_payload(dataset_id, features),
                overlay=overlay, center=center, pick_mode=pick_mode,
                status_labels=STATUS_LABELS, height=560)


def journey_overlay(features, state, result, fit_id=None):
    overlay = {'markers': [], 'route': [], 'connectors': [], 'bounds': [], 'fit_id': fit_id}
    for role, color in (('a', '#2563eb'), ('b', '#7c3aed')):
        lon, lat = state.get('route_'+role+'_lon'), state.get('route_'+role+'_lat')
        if lon is not None and lat is not None:
            overlay['markers'].append(dict(role=role.upper(), lon=lon, lat=lat, color=color))
    if result:
        chosen = result['routes'][state['route_choice']]
        route = route_features(features, chosen['edge_ids'], chosen['segments'])['features']
        overlay['route'] = compact_roads(route)
        for role in ('A', 'B'):
            if chosen['endpoint_gaps_m'][role] > .5:
                overlay['connectors'].append([[p[1], p[0]] for p in
                    (result['requested_coordinates'][role], chosen['snapped_coordinates'][role])])
        overlay['bounds'] = [[p[1], p[0]] for feature in route for p in feature['geometry']['coordinates']]
        overlay['bounds'].extend([[p[1], p[0]] for p in result['requested_coordinates'].values()])
    return overlay


def render_map(dataset_id, features, overlay, center, pick_mode, on_change):
    return _component(**component_arguments(dataset_id, st.session_state.get('porto_map'),
        features, overlay, center, pick_mode), key='porto_map', default={}, on_change=on_change)
