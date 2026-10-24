"""Device elements for libvirt domain XML."""

from __future__ import annotations

from lxml import etree

# Guest agents (spice-vdagent) look for this virtio port name.
SPICE_AGENT_PORT = "com.redhat.spice.0"


def vnc_graphics() -> etree._Element:
    """VNC display that listens nowhere: clients go through virDomainOpenGraphicsFD.

    virt-manager supports this listen type too, so the console stays reachable there.
    """
    graphics = etree.Element("graphics", type="vnc", sharePolicy="allow-exclusive")
    etree.SubElement(graphics, "listen", type="none")
    return graphics


def vdagent_channel(*, clipboard: bool = True) -> etree._Element:
    """QEMU's built-in vdagent: text clipboard and absolute mouse over VNC."""
    channel = etree.Element("channel", type="qemu-vdagent")
    source = etree.SubElement(channel, "source")
    etree.SubElement(source, "clipboard", copypaste="yes" if clipboard else "no")
    etree.SubElement(source, "mouse", mode="client")
    etree.SubElement(channel, "target", type="virtio", name=SPICE_AGENT_PORT)
    return channel


def use_qemu_vdagent(devices: etree._Element) -> bool:
    """Give the agent port to QEMU's vdagent, so copy and paste works over VNC.

    A SPICE agent channel (spicevmc, added by virt-manager) holds the same port
    name and cannot coexist with it: it is replaced. The SPICE display stays;
    SPICE clients just lose their own copy and paste. Returns True if changed.
    """
    if devices.find("channel[@type='qemu-vdagent']") is not None:
        return False
    for channel in devices.findall("channel"):
        target = channel.find("target")
        if target is not None and target.get("name") == SPICE_AGENT_PORT:
            devices.remove(channel)
    devices.append(vdagent_channel())
    return True
