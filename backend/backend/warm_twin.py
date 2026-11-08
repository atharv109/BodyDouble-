"""Pre-snapshot and pre-restore a twin for a later case (F17)."""
from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta

from contracts.models import CreateTwinRequest

from .db import WarmTwinRow, utcnow
from .state import build_state


async def warm_instance(state, instance_id: str) -> WarmTwinRow:
    source = await state.vultr.get_instance(instance_id)
    snapshot = await state.vultr.create_snapshot(
        instance_id, f"body-double warm twin for {instance_id}"
    )
    deadline = utcnow() + timedelta(seconds=state.settings.snapshot_timeout_s)
    while snapshot.status != "complete":
        if utcnow() > deadline:
            raise TimeoutError(f"snapshot {snapshot.id} did not complete")
        await asyncio.sleep(state.settings.poll_interval_s)
        snapshot = await state.vultr.get_snapshot(snapshot.id)

    vpc = await state.vultr.create_vpc(source.region, f"body-double warm {instance_id}")
    firewall = await state.vultr.create_firewall_group(
        f"bd warm {instance_id} inbound deny"
    )
    twin = await state.vultr.create_instance(CreateTwinRequest(
        region=source.region,
        plan=state.settings.twin_plan,
        label=f"bd-warm-{instance_id}",
        snapshot_id=snapshot.id,
        iso_id=state.settings.iso_id,
        attach_vpc=[vpc.id],
        firewall_group_id=firewall.id,
    ))
    deadline = utcnow() + timedelta(seconds=state.settings.boot_timeout_s)
    while twin.status != "active":
        if utcnow() > deadline:
            raise TimeoutError(f"warm twin {twin.id} did not boot")
        await asyncio.sleep(state.settings.poll_interval_s)
        twin = await state.vultr.get_instance(twin.id)

    row = WarmTwinRow(
        instance_id=instance_id, instance_label=source.label,
        snapshot_id=snapshot.id, twin_instance_id=twin.id,
        vpc_id=vpc.id, firewall_group_id=firewall.id,
        twin_internal_ip=twin.internal_ip,
        vpc_subnet=vpc.v4_subnet, vpc_mask=vpc.v4_subnet_mask,
        iso_id=state.settings.iso_id, created_at=utcnow(), adopted_at=None,
    )
    with state.sf() as session:
        session.add(row)
        session.commit()
        session.expunge(row)
    return row


async def _main(instance_id: str) -> None:
    state = build_state()
    try:
        row = await warm_instance(state, instance_id)
        print(f"warmed {row.instance_id}: snapshot={row.snapshot_id} twin={row.twin_instance_id}")
    finally:
        state.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Prebuild a Body Double warm twin")
    parser.add_argument("instance_id")
    args = parser.parse_args()
    asyncio.run(_main(args.instance_id))


if __name__ == "__main__":
    main()
