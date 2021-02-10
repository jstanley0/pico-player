# control a pair of TI SN76489 programmable sound generator ICs
# wiring: base pin on LSB (both chips in parallel)
#         base pin + 9 on left chip /WE
#         base pin + 8 on right chip /WE
#         both chips' /CE tied to GND, and both chips' READY disconnected

from rp2 import PIO, asm_pio, StateMachine
from machine import Pin

@asm_pio(set_init=PIO.OUT_LOW)
def __clock_prog():
    set(pins, 1)
    set(pins, 0)

@asm_pio(out_init=(PIO.OUT_LOW, PIO.OUT_LOW, PIO.OUT_LOW, PIO.OUT_LOW, PIO.OUT_LOW, PIO.OUT_LOW, PIO.OUT_LOW, PIO.OUT_LOW, PIO.OUT_HIGH, PIO.OUT_HIGH), out_shiftdir=PIO.SHIFT_RIGHT, set_init=(PIO.OUT_HIGH, PIO.OUT_HIGH))
def __xfer_prog():
    pull()
    out(pins, 10)[31]
    set(pins, 3)

class Sound:
    BASE_PIN = 0
    CLOCK_PIN = 15
    CLOCK_FREQ = 1_200_000
    LEFT = 0x200
    RIGHT = 0x100

    def __init__(self, base_pin = BASE_PIN, clock_pin = CLOCK_PIN, clock_freq = CLOCK_FREQ):
        self.base_pin = Pin(base_pin)
        self.we_pin = Pin(base_pin + 8)
        self.clock_pin = Pin(clock_pin)
        self.clock_freq = clock_freq

        self.__init_clock()
        self.__init_xfer()
        self.silence()

    def set_frequency(self, channel, voice, freq):
        self.__send_byte(channel, 0x80 | (voice << 5) | (freq & 0x0F))
        self.__send_byte(channel, freq >> 4)

    def set_attenuation(self, channel, voice, atten):
        self.__send_byte(channel, 0x90 | (voice << 5) | atten)

    def set_noise(self, channel, noise):
        self.__send_byte(channel, 0xE0 | noise)

    def silence(self):
        for voice in range(4):
            self.set_attenuation(Sound.LEFT, voice, 15)
            self.set_attenuation(Sound.RIGHT, voice, 15)

    def shutdown(self):
        self.silence()
        self.__stop_xfer()
        self.__stop_clock()

    def __init_clock(self):
        self.clock_sm = StateMachine(0, __clock_prog, freq=self.clock_freq*2, set_base=self.clock_pin)
        self.clock_sm.active(1)

    def __stop_clock(self):
        self.clock_sm.active(0)

    def __init_xfer(self):
        self.xfer_sm = StateMachine(1, __xfer_prog, freq=self.clock_freq, out_base=self.base_pin, set_base=self.we_pin)
        self.xfer_sm.active(1)

    def __stop_xfer(self):
        self.xfer_sm.active(0)

    def __send_byte(self, channel, byte):
        self.xfer_sm.put(channel | byte)

