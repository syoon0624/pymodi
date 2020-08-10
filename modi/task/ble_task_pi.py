import os
import json
import queue
import base64
from typing import Optional

import pygatt

from pygatt.exceptions import BLEError
from pygatt.exceptions import NotConnectedError

from modi.task.conn_task import ConnTask


class BleTask(ConnTask):
    char_uuid = "00008421-0000-1000-8000-00805F9B34FB"

    def __init__(self, verbose=False):
        super().__init__(verbose=verbose)

        self.adapter = pygatt.GATTToolBackend()
        self.device = None
        self._recv_q = queue.Queue()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close_conn()

    def open_conn(self):
        os.system("sudo hciconfig hci0 up")
        self.adapter.start()
        self.__connect("MODI_4DD5FA00")
        self.device.subscribe(self.char_uuid, callback=self.__ble_read)

    def close_conn(self):
        # Reboot modules to stop receiving channel messages
        self.send('{"c":9,"s":0,"d":4095,"b":"Bgg=","l":2}')
        self.adapter.stop()
        os.system("sudo hciconfig hci0 down")

    def __ble_read(self, value):
        """
        handle -- integer, characteristic read handle the data was received on
        value -- bytearray, the data returned in the notification
        """
        json_msg = self.__parse_ble_msg(value)
        if self.verbose:
            print(f"recv: {json_msg}")
        self._recv_q.put(json_msg)

    def send(self, pkt: str) -> None:
        json_msg = json.loads(pkt)
        ble_msg = self.__compose_ble_msg(json_msg)

        self.device.char_write(self.char_uuid, ble_msg)

    def recv(self) -> Optional[str]:
        if self._recv_q.empty():
            return None
        return self._recv_q.get()

    #
    # Ble Helper Methods
    #
    def __compose_ble_msg(self, json_msg):
        ble_msg = bytearray(16)

        ins = json_msg["c"]
        sid = json_msg["s"]
        did = json_msg["d"]
        dlc = json_msg["l"]
        data = json_msg["b"]

        ble_msg[0] = ins & 0xFF
        ble_msg[1] = ins >> 8 & 0xFF
        ble_msg[2] = sid & 0xFF
        ble_msg[3] = sid >> 8 & 0xFF
        ble_msg[4] = did & 0xFF
        ble_msg[5] = did >> 8 & 0xFF
        ble_msg[6] = dlc & 0xFF
        ble_msg[7] = dlc >> 8 & 0xFF

        ble_msg[8:8+dlc] = bytearray(base64.b64decode(data))

        return ble_msg

    def __parse_ble_msg(self, ble_msg):
        json_msg = dict()
        json_msg["c"] = ble_msg[1] << 8 | ble_msg[0]
        json_msg["s"] = ble_msg[3] << 8 | ble_msg[2]
        json_msg["d"] = ble_msg[5] << 8 | ble_msg[4]
        json_msg["l"] = ble_msg[7] << 8 | ble_msg[6]
        json_msg["b"] = base64.b64encode(ble_msg[8:]).decode("utf-8")
        return json.dumps(json_msg, separators=(",", ":"))

    def __connect(self, target_name, max_retries=3):
        target_addr = self.__find_addr(target_name)

        while max_retries <= 3:
            print("Try connecting to name: {}, addr: {}".format(
                target_name, target_addr))

            try:
                device = self.adapter.connect(address=target_addr, timeout=10)
            except NotConnectedError:
                max_retries -= 1
                continue
            break

        print("Successfully connected to the target device")
        self.device = device

    def __find_addr(self, target_name, max_retries=5):
        """ Given target device name, find corresponding device address
        """

        target_addr = None
        while target_addr is None:
            if max_retries < 0:
                raise ValueError("Cannot connect to the target_device")

            try:
                scanned_devices = self.adapter.scan(run_as_root=True)
            except BLEError:
                max_retries -= 1

                # Re-initializing hci interface for re-scanning properly
                os.system("sudo hciconfig hci0 down")
                os.system("sudo hciconfig hci0 up")
                continue

            for scanned_device in scanned_devices:
                device_name = scanned_device["name"]
                device_addr = scanned_device["address"]

                if device_name is None:
                    continue

                if device_name == target_name:
                    target_addr = device_addr
                    break

            max_retries -= 1

        return target_addr
