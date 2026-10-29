from blueprint.models import Interval, IntervalUnit, MaintenanceTask


def task(component, action, *intervals, parts=(), asset="A1", **extra):
    """task('oil filter', 'replace', (500, 'hours'), (6, 'months'), spec='SAE 15W-40')"""
    return MaintenanceTask(
        asset_id=asset,
        component=component,
        action=action,
        part_ids=list(parts),
        intervals=[Interval(value=v, unit=IntervalUnit(u)) for v, u in intervals],
        **extra,
    )
