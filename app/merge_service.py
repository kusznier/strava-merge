"""Łączenie dwóch aktywności w jeden TCX (logika zbliżona do strava_merge.py)."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET

from stravalib import Client
from stravalib.model import Stream


def _create_points(streams: dict, start_time: datetime) -> list[dict]:
    points = []
    times = streams.get("time", Stream()).data if "time" in streams else []
    latlngs = streams.get("latlng", Stream()).data if "latlng" in streams else []
    distances = streams.get("distance", Stream()).data if "distance" in streams else []
    altitudes = streams.get("altitude", Stream()).data if "altitude" in streams else []
    heartrates = streams.get("heartrate", Stream()).data if "heartrate" in streams else []
    cadences = streams.get("cadence", Stream()).data if "cadence" in streams else []
    wattss = streams.get("watts", Stream()).data if "watts" in streams else []

    for i in range(len(times)):
        point = {
            "time": start_time + timedelta(seconds=times[i]),
            "lat": latlngs[i][0] if i < len(latlngs) else None,
            "lon": latlngs[i][1] if i < len(latlngs) else None,
            "distance": distances[i] if i < len(distances) else None,
            "altitude": altitudes[i] if i < len(altitudes) else None,
            "heartrate": heartrates[i] if i < len(heartrates) else None,
            "cadence": cadences[i] if i < len(cadences) else None,
            "watts": wattss[i] if i < len(wattss) else None,
        }
        points.append(point)
    return points


def merge_two_activities_to_tcx(
    client: Client,
    act1_id: int,
    act2_id: int,
    output_path: Path,
) -> None:
    first = client.get_activity(act1_id)
    second = client.get_activity(act2_id)
    first_id, second_id = act1_id, act2_id

    # Chronologia: wcześniejsza pierwsza
    if second.start_date < first.start_date:
        first, second = second, first
        first_id, second_id = second_id, first_id

    sport = str(first.type)

    types = ["time", "latlng", "distance", "altitude", "heartrate", "cadence", "watts"]
    streams1 = client.get_activity_streams(first_id, types=types)
    streams2 = client.get_activity_streams(second_id, types=types)

    points1 = _create_points(streams1, first.start_date)
    points2 = _create_points(streams2, second.start_date)

    if points1 and points2:
        max_dist1 = max((p["distance"] for p in points1 if p["distance"] is not None), default=0)
        for p in points2:
            if p["distance"] is not None:
                p["distance"] += max_dist1

    all_points = points1 + points2
    all_points.sort(key=lambda p: p["time"])

    root = ET.Element(
        "TrainingCenterDatabase",
        xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2",
    )
    activities_elem = ET.SubElement(root, "Activities")
    activity_elem = ET.SubElement(activities_elem, "Activity", Sport=sport)
    id_elem = ET.SubElement(activity_elem, "Id")
    id_elem.text = datetime.now().isoformat()

    lap = ET.SubElement(
        activity_elem,
        "Lap",
        StartTime=all_points[0]["time"].isoformat() if all_points else datetime.now().isoformat(),
    )
    total_time = ET.SubElement(lap, "TotalTimeSeconds")
    total_time.text = str(int(first.elapsed_time + second.elapsed_time))
    distance_elem = ET.SubElement(lap, "DistanceMeters")
    distance_elem.text = str(float(first.distance) + float(second.distance))

    track = ET.SubElement(lap, "Track")
    for point in all_points:
        tp = ET.SubElement(track, "Trackpoint")
        time_elem = ET.SubElement(tp, "Time")
        time_elem.text = point["time"].isoformat()
        if point["lat"] is not None and point["lon"] is not None:
            position = ET.SubElement(tp, "Position")
            lat = ET.SubElement(position, "LatitudeDegrees")
            lat.text = str(point["lat"])
            lon = ET.SubElement(position, "LongitudeDegrees")
            lon.text = str(point["lon"])
        if point["altitude"] is not None:
            alt = ET.SubElement(tp, "AltitudeMeters")
            alt.text = str(point["altitude"])
        if point["distance"] is not None:
            dist = ET.SubElement(tp, "DistanceMeters")
            dist.text = str(point["distance"])
        if point["heartrate"] is not None:
            hrbpm = ET.SubElement(tp, "HeartRateBpm")
            value = ET.SubElement(hrbpm, "Value")
            value.text = str(point["heartrate"])

    tree = ET.ElementTree(root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(output_path), encoding="unicode", xml_declaration=True)


def merge_to_tempfile(client: Client, act1_id: int, act2_id: int) -> str:
    fd, path = tempfile.mkstemp(suffix=".tcx", prefix="merged_")
    import os

    os.close(fd)
    merge_two_activities_to_tcx(client, act1_id, act2_id, Path(path))
    return path
