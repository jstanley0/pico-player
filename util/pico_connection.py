import serial
from serial.tools import list_ports
from pyboard import Pyboard

class PicoConnection:
    def __init__(self):
        self.pyboard = None # to prevent another exception in the destructor if initialization fails
        self.pyboard = Pyboard(self._find_pico_port())

    # borrowed from https://github.com/dhylands/rshell/blob/master/rshell/main.py
    def _is_pico_usb_device(self, port):
        if type(port).__name__ == 'Device':
            # Assume its a pyudev.device.Device
            if ('ID_BUS' not in port or port['ID_BUS'] != 'usb' or
                'SUBSYSTEM' not in port or port['SUBSYSTEM'] != 'tty'):
                return False
            usb_id = 'usb vid:pid={}:{}'.format(port['ID_VENDOR_ID'], port['ID_MODEL_ID'])
        else:
            # Assume its a port from serial.tools.list_ports.comports()
            usb_id = port[2].lower()

        if usb_id.startswith('usb vid:pid=2e8a:0005'):
            global USB_BUFFER_SIZE
            USB_BUFFER_SIZE = 128
            return True

        return False

    def _find_pico_port(self):
        for port in serial.tools.list_ports.comports():
            if self._is_pico_usb_device(port):
                return port.device
        raise RuntimeError("Pico not found")

    def _send_command_queue(self, commands):
        #print(commands)
        self.pyboard.exec(f't=m.play_words({commands},t)\r\n')

    def play_song(self, buf):
        try:
            self.pyboard.enter_raw_repl()
            self.pyboard.exec("import utime\r\n")
            self.pyboard.exec("from music_player import MusicPlayer\r\n")
            self.pyboard.exec("m=MusicPlayer()\r\n")
            self.pyboard.exec("m.start_playing()\r\n")
            self.pyboard.exec("t=utime.ticks_ms()\r\n")
            bytes = buf.read(2)
            command_queue = []
            while bytes:
                cmd = int.from_bytes(bytes, byteorder='big')
                # wait until a suitably long delay to send a command string,
                # (or if the queue grows too long, send it anyway and risk an audible hiccup)
                if len(command_queue) > 100 or ((cmd & 0xc000) == 0x8000 and (cmd & 0x3fff) > 100):
                    self._send_command_queue(command_queue)
                    command_queue.clear()
                command_queue.append(cmd)
                bytes = buf.read(2)
            # send remaining commands followed by a one-second delay so notes can fade
            command_queue.append(0x83e8)
            self._send_command_queue(command_queue)
            self.pyboard.exec("m.finish_playing()")
        except KeyboardInterrupt:
            # force a Ctrl+C to be sent to the Pico
            self.pyboard.enter_raw_repl()
        finally:
            self.pyboard.exit_raw_repl()
