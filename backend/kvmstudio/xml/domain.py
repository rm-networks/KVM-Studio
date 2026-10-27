"""libvirt domain XML for a new VM, built element by element (never by f-strings)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .devices import vdagent_channel, vnc_graphics
from .profiles import DiskBus, NicModel, Profile

NAMESPACE = "https://github.com/rm-networks/kvm-studio/ns/1.0"

# PCIe slots of a q35 VM, as virt-manager makes them: its devices take about
# half, the rest stay free for disks, cards and controllers added while it runs.
ROOT_PORTS = 14

# Disk target name prefix for each bus.
_TARGET_PREFIX: dict[str, str] = {
    "virtio": "vd",
    "scsi": "sd",
    "sata": "sd",
    "ide": "hd",
    "nvme": "nvme",
}


@dataclass(frozen=True, slots=True)
class DiskSpec:
    path: Path
    format: str  # "qcow2" or "raw"
    bus: DiskBus


@dataclass(frozen=True, slots=True)
class NicSpec:
    network: str
    model: NicModel
    target: str  # host interface name, ks-<id>-<n>


@dataclass(slots=True)
class DomainSpec:
    name: str
    uuid: str
    profile: Profile
    memory_mib: int
    vcpus: int
    disks: list[DiskSpec]
    iso: Path | None
    nics: list[NicSpec]
    uefi: bool
    secure_boot: bool
    tpm: bool
    nvram: Path | None
    folder: str
    domain_type: str = "kvm"
    # Versioned machine type (pc-q35-10.2): the VM keeps the same virtual
    # hardware when QEMU is updated. "q35" only where libvirt gives none.
    machine: str = "q35"
    # Host processor, for the virtualization extension a nested profile needs.
    cpu_vendor: str | None = None
    extra_cdroms: list[Path] = field(default_factory=list)
    # Library root the folder is relative to (services.library.LIBRARY_KEY).
    library: str = ""


def _sub(parent: etree._Element, tag: str, text: str | None = None, **attrs: str) -> etree._Element:
    el = etree.SubElement(parent, tag, attrib=attrs)
    if text is not None:
        el.text = text
    return el


def _targets(bus: str) -> list[str]:
    prefix = _TARGET_PREFIX[bus]
    if bus == "nvme":
        return [f"nvme{i}n1" for i in range(16)]
    return [f"{prefix}{chr(ord('a') + i)}" for i in range(26)]


def build_domain(spec: DomainSpec) -> str:
    p = spec.profile
    root = etree.Element("domain", type=spec.domain_type)
    _sub(root, "name", spec.name)
    _sub(root, "uuid", spec.uuid)
    metadata = _sub(root, "metadata")
    vm = etree.SubElement(metadata, f"{{{NAMESPACE}}}vm", nsmap={"kvmstudio": NAMESPACE})
    etree.SubElement(vm, f"{{{NAMESPACE}}}folder").text = spec.folder
    etree.SubElement(vm, f"{{{NAMESPACE}}}profile").text = p.id
    if spec.library:
        etree.SubElement(vm, f"{{{NAMESPACE}}}library").text = spec.library
    _sub(root, "memory", str(spec.memory_mib), unit="MiB")
    _sub(root, "currentMemory", str(spec.memory_mib), unit="MiB")
    _sub(root, "vcpu", str(spec.vcpus), placement="static")

    os_el = _sub(root, "os", firmware="efi") if spec.uefi else _sub(root, "os")
    _sub(os_el, "type", "hvm", arch="x86_64", machine=spec.machine)
    if spec.uefi:
        firmware = _sub(os_el, "firmware")
        _sub(firmware, "feature", enabled="yes" if spec.secure_boot else "no", name="secure-boot")
        _sub(firmware, "feature", enabled="yes" if spec.secure_boot else "no", name="enrolled-keys")
        if spec.secure_boot:
            _sub(os_el, "loader", secure="yes")
        if spec.nvram is not None:
            # In the VM's own folder (spec 6.1.1); libvirt fills it from the template.
            _sub(os_el, "nvram", str(spec.nvram))
    _sub(os_el, "boot", dev="hd")
    _sub(os_el, "boot", dev="cdrom")
    _sub(os_el, "bootmenu", enable="yes", timeout="3000")

    features = _sub(root, "features")
    _sub(features, "acpi")
    _sub(features, "apic")
    if spec.secure_boot:
        _sub(features, "smm", state="on")
    if p.family == "windows":
        hyperv = _sub(features, "hyperv", mode="custom")
        for name in ("relaxed", "vapic", "vpindex", "runtime", "synic", "reset", "frequencies"):
            _sub(hyperv, name, state="on")
        _sub(hyperv, "spinlocks", state="on", retries="8191")
        _sub(hyperv, "stimer", state="on")
    _sub(features, "vmport", state="off")

    cpu = _sub(root, "cpu", mode="host-passthrough", check="none", migratable="on")
    if p.nested and spec.cpu_vendor in ("intel", "amd"):
        flag = "vmx" if spec.cpu_vendor == "intel" else "svm"
        _sub(cpu, "feature", policy="require", name=flag)
    clock = _sub(root, "clock", offset="localtime" if p.family == "windows" else "utc")
    _sub(clock, "timer", name="rtc", tickpolicy="catchup")
    _sub(clock, "timer", name="pit", tickpolicy="delay")
    _sub(clock, "timer", name="hpet", present="no")
    if p.family == "windows":
        _sub(clock, "timer", name="hypervclock", present="yes")
    _sub(root, "on_poweroff", "destroy")
    _sub(root, "on_reboot", "restart")
    _sub(root, "on_crash", "destroy")
    pm = _sub(root, "pm")
    _sub(pm, "suspend-to-mem", enabled="no")
    _sub(pm, "suspend-to-disk", enabled="no")

    devices = _sub(root, "devices")
    used: dict[str, set[str]] = {}

    def next_target(bus: str) -> str:
        taken = used.setdefault(bus if bus != "scsi" else "sata", set())
        for name in _targets(bus):
            if name not in taken:
                taken.add(name)
                return name
        raise ValueError(f"too many {bus} devices")

    if any(d.bus == "scsi" for d in spec.disks):
        _sub(devices, "controller", type="scsi", model="virtio-scsi")
    for disk in spec.disks:
        el = _sub(devices, "disk", type="file", device="disk")
        _sub(el, "driver", name="qemu", type=disk.format, discard="unmap")
        _sub(el, "source", file=str(disk.path))
        _sub(el, "target", dev=next_target(disk.bus), bus=disk.bus)
    for iso in [spec.iso, *spec.extra_cdroms]:
        el = _sub(devices, "disk", type="file", device="cdrom")
        _sub(el, "driver", name="qemu", type="raw")
        if iso is not None:
            _sub(el, "source", file=str(iso))
        _sub(el, "target", dev=next_target("sata"), bus="sata")
        _sub(el, "readonly")

    for nic in spec.nics:
        el = _sub(devices, "interface", type="network")
        _sub(el, "source", network=nic.network)
        _sub(el, "model", type=nic.model)
        _sub(el, "target", dev=nic.target)

    _sub(devices, "controller", type="usb", model="qemu-xhci", ports="15")
    if "q35" in spec.machine:
        # The root first: an unnumbered controller would otherwise claim index 0.
        _sub(devices, "controller", type="pci", index="0", model="pcie-root")
        for _ in range(ROOT_PORTS):
            _sub(devices, "controller", type="pci", model="pcie-root-port")
    _sub(devices, "input", type="tablet", bus="usb")
    devices.append(vnc_graphics())
    devices.append(vdagent_channel())
    agent = _sub(devices, "channel", type="unix")
    _sub(agent, "target", type="virtio", name="org.qemu.guest_agent.0")
    video = _sub(devices, "video")
    _sub(video, "model", type=p.video, heads="1", primary="yes")
    if p.serial:
        serial = _sub(devices, "serial", type="pty")
        _sub(serial, "target", port="0")
        console = _sub(devices, "console", type="pty")
        _sub(console, "target", type="serial", port="0")
    if spec.tpm:
        tpm = _sub(devices, "tpm", model="tpm-crb")
        _sub(tpm, "backend", type="emulator", version="2.0")
    rng = _sub(devices, "rng", model="virtio")
    _sub(rng, "backend", "/dev/urandom", model="random")
    _sub(devices, "memballoon", model="virtio")
    return etree.tostring(root, pretty_print=True).decode()
