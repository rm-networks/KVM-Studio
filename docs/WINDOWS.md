# Windows guests

Settings that matter for a responsive Windows VM, what KVM Studio sets for new
VMs, and how to check an existing one. Nothing on this page is applied to an
existing VM automatically.

Status: the settings below were checked with libvirt and QEMU (the VM is
accepted and starts up to its UEFI firmware). They were not validated on a
Windows guest by the project; the measurement procedure at the end of this
page is how to do it.

## What a new Windows VM gets

The assistant's Windows 10, Windows 11 and Windows Server profiles produce:

| Area | Setting |
|---|---|
| CPU | `host-passthrough` |
| Clock | `localtime`; `rtc` catchup, `pit` delay, `hpet` off, `hypervclock` on |
| Hyper-V enlightenments | relaxed, vapic, spinlocks (8191), vpindex, runtime, synic, stimer, reset, frequencies, tlbflush, ipi |
| Pointer | USB tablet (absolute), and the mouse of the QEMU vdagent channel once the guest tools run |
| Disk | SATA, so that Windows setup finds it without drivers |
| Network | e1000e, same reason |
| Display | `bochs` |
| Firmware | UEFI; Secure Boot for 11 and Server, TPM 2.0 for 11 |

Since 1.1.3, `tlbflush` and `ipi` are added: Windows then flushes the TLB of
other vCPUs and sends them interrupts with a hypercall instead of exits the
hypervisor has to emulate, which matters more as the vCPU count grows.

### Compared with virt-install

`virt-install --print-xml` (virt-install 5.1, libvirt 12.6, QEMU 11.1) for
`--osinfo win10`, `win11` and `win2k22` gives the same CPU mode, clock, timers,
tablet and e1000e card. Differences:

| Setting | virt-install | KVM Studio | Note |
|---|---|---|---|
| `tlbflush`, `ipi` | on | on since 1.1.3 | |
| `evmcs` | on | off | Intel hosts only; helps when Windows runs Hyper-V itself (VBS, WSL 2). Not set by default because it depends on the host CPU. |
| `avic` | on | off | AMD hosts only. Same reason. |
| `reset` | off | on | Lets Windows reset the VM through Hyper-V; harmless. |
| Video | `bochs` (11), `vga` (10, 2022) | `bochs` | |
| CPU topology | none | none | See below. |

## CPU topology: check it first

Without a `<topology>` element, libvirt gives QEMU one socket per vCPU
(`-smp 4,sockets=4,cores=1,threads=1`). Windows 10 and 11 limit the sockets
they use: one for Home, two for Pro and Education. A Pro VM with four vCPUs
then runs on two of them. Windows Server editions accept more sockets.

In Windows, Task Manager > Performance > CPU shows "Sockets" and "Logical
processors". If Sockets is greater than what the edition uses, give the VM a
single socket:

```bash
virsh -c qemu:///system edit CLT-W10
```

and in `<cpu ...>`, with N the number of vCPUs:

```xml
<cpu mode='host-passthrough' check='none' migratable='on'>
  <topology sockets='1' dies='1' cores='N' threads='1'/>
</cpu>
```

Changing the vCPU count later in Settings > Hardware removes this element (the
count must match it): add it again afterwards.

## Recommended for an existing Windows VM

With the VM powered off, `virsh -c qemu:///system edit <vm>`:

1. Under `<features><hyperv mode='custom'>`, add the two lines below if they
   are missing:

   ```xml
   <tlbflush state='on'/>
   <ipi state='on'/>
   ```

   On an Intel host with Hyper-V features turned on in Windows (VBS, WSL 2),
   `<evmcs state='on'/>` can be added too; on an AMD host, `<avic state='on'/>`.
2. The CPU topology above, for a client edition with more sockets than it uses.
3. After the guest tools (VM > Install Guest Tools), the virtio disk and
   network drivers are installed; moving the system disk to VirtIO is a
   separate, manual step not covered here.

Check that libvirt kept the lines:

```bash
virsh -c qemu:///system dumpxml <vm> | grep -E "tlbflush|ipi|topology"
```

## What was measured

KVM Studio does not draw the guest picture: QEMU's VNC server does, and the
console relays it to noVNC. What KVM Studio adds was measured on a Linux guest
(Debian 13, Plasma), in a nested VM, by the same VNC client connected straight
to QEMU through libvirt, then through the console relay (web mode, 127.0.0.1),
40 key presses each, time from the key to the first screen update:

| Path | Median | 90th percentile |
|---|---|---|
| QEMU VNC, direct | 82.3 ms | 83.0 ms |
| Console relay, 1.1.1 | 84.7 ms | 85.5 ms |
| Console relay, 1.1.2 | 84.7 ms | 85.9 ms |
| Console relay, 1.1.3 | 84.7 ms | 85.1 ms |
| Console relay, WebSocket compression off | 84.4 ms | 84.9 ms |

The relay adds about 2.5 ms; the WebSocket compression about 0.3 ms. The
update rate with on-screen activity was the same direct and through the relay.
The remaining time is QEMU's update cycle and the guest itself. Absolute values
from a nested VM say nothing about a laptop: compare on the same machine.

## Measuring on a Windows VM

On the host, with the VM running, the same steps before and after a change:

1. Window mode, then web mode (Firefox and a Chromium-based browser), same VM,
   same window size. Move a window in circles for 10 s, scroll a long page,
   type in Notepad; note what feels slower.
2. Frame rate seen by the page: in a Chromium-based browser, DevTools > More
   tools > Rendering > Frame rendering stats. For window mode, start it with
   `QTWEBENGINE_REMOTE_DEBUGGING=127.0.0.1:9223 kvm-studio --mode desktop` and
   open `http://127.0.0.1:9223` in a Chromium-based browser to get the same
   DevTools.
3. VM exits, which the enlightenments reduce, over 30 s of the same activity:

   ```bash
   sudo perf kvm stat record -p $(pgrep -f 'guest=CLT-W10') -o /tmp/kvm.data sleep 30
   ```

   ```bash
   sudo perf kvm stat report -i /tmp/kvm.data | head -20
   ```

4. CPU used by QEMU for the same activity:

   ```bash
   top -b -d 5 -n 6 -p $(pgrep -f 'guest=CLT-W10') | grep qemu
   ```

Report the values with the host CPU model, the Windows edition and version, the
vCPU count and topology, the display model and the KVM Studio version.
