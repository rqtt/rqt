"""
Windows doesn't expose temperatures or fan speeds through any API that works
without a kernel driver. LibreHardwareMonitor ships that driver, and while it's
running it publishes every sensor over WMI, so on Windows we just read those.

If LHM (or the older OpenHardwareMonitor) isn't running, everything here
quietly reports "not available" and the rest of the app carries on.
"""
import logging
import sys

log = logging.getLogger(__name__)

NAMESPACES = ("root\\LibreHardwareMonitor", "root\\OpenHardwareMonitor")


class LibreHardwareMonitor:
    def __init__(self):
        self._conn = None
        self._hw_names = {}
        if sys.platform != "win32":
            return
        try:
            import pythoncom
            import wmi
        except ImportError:
            log.info("pywin32/wmi not installed, skipping LibreHardwareMonitor")
            return

        # COM has to be initialised on whichever thread uses it, and the
        # sampler runs on a worker thread.
        pythoncom.CoInitialize()

        for ns in NAMESPACES:
            try:
                conn = wmi.WMI(namespace=ns)
                hardware = conn.Hardware()
            except Exception:
                continue
            if hardware:
                self._conn = conn
                self._hw_names = {h.Identifier: h.Name for h in hardware}
                log.info("reading sensors from %s (%d devices)", ns, len(hardware))
                break

    @property
    def available(self):
        return self._conn is not None

    def sensors(self):
        """Returns [(parent_id, hardware_name, sensor_type, name, value), ...]"""
        if self._conn is None:
            return []
        try:
            rows = self._conn.Sensor()
        except Exception as e:
            # LHM was closed while we were running
            log.warning("lost LibreHardwareMonitor: %s", e)
            self._conn = None
            return []
        return [
            (r.Parent, self._hw_names.get(r.Parent, r.Parent), r.SensorType, r.Name, r.Value)
            for r in rows
        ]
