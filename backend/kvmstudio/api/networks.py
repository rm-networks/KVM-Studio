from __future__ import annotations

import ipaddress
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import helper_client
from ..context import Context
from ..errors import ApiException
from ..services import networks as net

router = APIRouter(prefix="/networks", tags=["networks"])


class Dhcp(BaseModel):
    start: str
    end: str


class Network(BaseModel):
    name: str
    kind: net.Kind
    forward_mode: str | None
    bridge: str | None
    managed: bool
    active: bool
    autostart: bool
    persistent: bool
    subnet: str | None
    host_ip: str | None
    dhcp: Dhcp | None
    gateway: net.GatewayMode = "host"
    gateway_ip: str | None = None


class NetworkSettings(BaseModel):
    kind: net.EditableKind
    subnet: str | None = None
    host_adapter: bool = True
    dhcp: Dhcp | None = None
    host_ip: str | None = None
    # None: libvirt's default (the host on NAT, no gateway on host-only).
    gateway: net.GatewayMode | None = None
    gateway_ip: str | None = None

    def to_spec(self) -> net.NetworkSpec:
        try:
            subnet = ipaddress.IPv4Network(self.subnet) if self.subnet else None
        except ValueError as exc:
            raise ApiException(422, "net.bad_subnet", str(exc)) from exc
        dhcp = net.DhcpRange(self.dhcp.start, self.dhcp.end) if self.dhcp else None
        return net.NetworkSpec(
            self.kind,
            subnet,
            self.host_adapter,
            dhcp,
            self.host_ip or None,
            self.gateway,
            self.gateway_ip if self.gateway == "custom" else None,
        )


class NetworkUpdate(NetworkSettings):
    # Asked after the confirmation: stop the running VMs that use the network.
    stop_vms: Literal["shutdown", "poweroff"] | None = None


class PortForward(BaseModel):
    """A NAT port forwarding rule, written by the administrator; the helper checks it."""

    proto: Literal["tcp", "udp"]
    host_address: str = "127.0.0.1"
    host_port: int
    vm_ip: str
    vm_port: int
    description: str = ""


class PortForwards(BaseModel):
    rules: list[PortForward]


class PortsInUse(BaseModel):
    tcp: list[int]
    udp: list[int]


class UpdatePlan(BaseModel):
    restart: bool
    running: list[str]


class NetworkCreate(NetworkSettings):
    name: str | None = None
    number: int | None = Field(default=None, ge=1, le=net.MAX_NUMBER)
    autostart: bool = True


class NetworkRename(BaseModel):
    name: str


class NetworkState(BaseModel):
    active: bool | None = None
    autostart: bool | None = None


class Suggestion(BaseModel):
    name: str
    number: int
    subnet: str
    dhcp: Dhcp


class NetworkExport(BaseModel):
    format: Literal["kvm-studio-networks"] = "kvm-studio-networks"
    version: Literal[1] = 1
    networks: list[NetworkCreate]


class ImportReport(BaseModel):
    created: list[str]
    skipped: list[str]


def _model(info: net.NetworkInfo) -> Network:
    return Network(
        name=info.name,
        kind=info.kind,
        forward_mode=info.forward_mode,
        bridge=info.bridge,
        managed=info.managed,
        active=info.active,
        autostart=info.autostart,
        persistent=info.persistent,
        subnet=info.subnet,
        host_ip=info.host_ip,
        dhcp=Dhcp(start=info.dhcp.start, end=info.dhcp.end) if info.dhcp else None,
        gateway=info.gateway,
        gateway_ip=info.gateway_ip,
    )


@router.get("")
async def list_all(ctx: Context) -> list[Network]:
    return [_model(n) for n in await run_in_threadpool(net.list_networks, ctx.conn)]


@router.get("/suggestion")
async def suggestion(ctx: Context) -> Suggestion:
    """Free kvmnet number and subnet for the "Add network" button."""

    def run() -> Suggestion:
        number = net.free_number(ctx.conn)
        subnet = net.free_subnet(ctx.conn, net.host_subnets(), 100 + number)
        dhcp = net.default_dhcp(subnet)
        return Suggestion(
            name=f"{net.BRIDGE_PREFIX}{number}",
            number=number,
            subnet=str(subnet),
            dhcp=Dhcp(start=dhcp.start, end=dhcp.end),
        )

    return await run_in_threadpool(run)


@router.post("", status_code=201)
async def create(ctx: Context, body: NetworkCreate) -> Network:
    def run() -> Network:
        number = body.number or net.free_number(ctx.conn)
        name = body.name or f"{net.BRIDGE_PREFIX}{number}"
        net.create_network(ctx.conn, name, number, body.to_spec(), autostart=body.autostart)
        return next(_model(n) for n in net.list_networks(ctx.conn) if n.name == name)

    return await run_in_threadpool(run)


@router.post("/{name}/plan")
async def plan(ctx: Context, name: str, body: NetworkSettings) -> UpdatePlan:
    """Whether these settings restart the network, and which running VMs use it."""
    found = await run_in_threadpool(net.plan_update, ctx.conn, name, body.to_spec())
    return UpdatePlan(restart=found.restart, running=list(found.running))


@router.put("/{name}", status_code=204)
async def update(ctx: Context, name: str, body: NetworkUpdate) -> Response:
    await run_in_threadpool(
        lambda: net.update_network(ctx.conn, name, body.to_spec(), stop_vms=body.stop_vms)
    )
    return Response(status_code=204)


@router.post("/{name}/rename", status_code=204)
async def rename(ctx: Context, name: str, body: NetworkRename) -> Response:
    await run_in_threadpool(net.rename_network, ctx.conn, name, body.name)
    return Response(status_code=204)


@router.patch("/{name}", status_code=204)
async def set_state(ctx: Context, name: str, body: NetworkState) -> Response:
    await run_in_threadpool(
        lambda: net.set_state(ctx.conn, name, active=body.active, autostart=body.autostart)
    )
    return Response(status_code=204)


@router.delete("/{name}", status_code=204)
async def delete(ctx: Context, name: str) -> Response:
    await run_in_threadpool(net.delete_network, ctx.conn, name)
    # Its port forwarding rules go with it (the helper asks for the password).
    try:
        if await run_in_threadpool(_forwards, name):
            await run_in_threadpool(
                helper_client.call, "set_port_forwards", {"network": name, "rules": []}
            )
    except ApiException:
        pass  # no helper: nothing was forwarded through it
    return Response(status_code=204)


def _forwards(name: str) -> list[dict[str, object]]:
    networks = helper_client.call("list_port_forwards", {}).get("networks", {})
    return list(networks.get(name, []))


@router.get("/{name}/forwards")
async def forwards(name: str) -> PortForwards:
    rules = await run_in_threadpool(_forwards, name)
    return PortForwards(rules=[PortForward.model_validate(r) for r in rules])


@router.put("/{name}/forwards")
async def set_forwards(name: str, body: PortForwards) -> PortForwards:
    """Root operation: the helper checks every rule and asks for the password."""
    params = {"network": name, "rules": [r.model_dump() for r in body.rules]}
    await run_in_threadpool(helper_client.call, "set_port_forwards", params)
    return await forwards(name)


@router.get("/host/ports-in-use")
async def ports_in_use() -> PortsInUse:
    """Ports something on the host already listens on (shown as information only)."""
    return PortsInUse(**await run_in_threadpool(net.listening_ports))


@router.post("/defaults")
async def defaults(ctx: Context) -> list[str]:
    return await run_in_threadpool(net.restore_defaults, ctx.conn)


@router.get("/export")
async def export(ctx: Context) -> NetworkExport:
    networks = await run_in_threadpool(net.list_networks, ctx.conn)
    exported = []
    for n in networks:
        if n.kind == "other" or not n.managed or n.bridge is None:
            continue
        exported.append(
            NetworkCreate(
                name=n.name,
                number=int(n.bridge.removeprefix(net.BRIDGE_PREFIX)),
                kind=n.kind,
                subnet=n.subnet,
                host_adapter=n.host_ip is not None,
                dhcp=Dhcp(start=n.dhcp.start, end=n.dhcp.end) if n.dhcp else None,
                autostart=n.autostart,
            )
        )
    return NetworkExport(networks=exported)


@router.post("/import")
async def import_networks(ctx: Context, body: NetworkExport) -> ImportReport:
    """Create the networks of an export that do not exist yet; nothing is overwritten."""

    def run() -> ImportReport:
        report = ImportReport(created=[], skipped=[])
        for item in body.networks:
            existing = {n.name for n in net.list_networks(ctx.conn)}
            number = item.number or net.free_number(ctx.conn)
            name = item.name or f"{net.BRIDGE_PREFIX}{number}"
            if name in existing:
                report.skipped.append(name)
                continue
            try:
                net.create_network(ctx.conn, name, number, item.to_spec(), autostart=item.autostart)
            except ApiException:
                report.skipped.append(name)
            else:
                report.created.append(name)
        return report

    return await run_in_threadpool(run)
