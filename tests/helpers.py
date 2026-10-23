from blueprint.models import Interval, IntervalUnit, MaintenanceTask


def task(component, action, *intervals, parts=(), asset="A1"):
    """task('oil filter', 'replace', (500, 'hours'), (6, 'months'))"""
    return MaintenanceTask(
        asset_id=asset,
        component=component,
        action=action,
        part_ids=list(parts),
        intervals=[Interval(value=v, unit=IntervalUnit(u)) for v, u in intervals],
    )
