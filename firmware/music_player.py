import utime
import math
from array import array
from machine import Pin, PWM, Timer
from sound import Sound

def read_words(filename):
    buffer = bytearray(128)
    with open(filename, 'rb', buffering=0) as file:
        while True:
            n = file.readinto(buffer)
            if n == 0:
                break
            i = 0
            while i + 1 < n:
                yield (buffer[i] << 8) | buffer[i + 1]
                i += 2

class MusicPlayer:
    LED_PINS = [16, 17, 18, None, 19, 20, 21, None]
    def __init__(self):
        self.sound = Sound()
        self.__init_frequency_table()
        self.atten = [15] * 8
        self.target = [15] * 8
        self.__init_leds()
        self.timer = Timer()

    def play_song(self, filename):
        try:
            self.timer.init(freq=20, mode=Timer.PERIODIC, callback=self.__process_envelopes)
            for word in read_words(filename):
                if word & 0x8000 == 0:
                    # note on: V = voice; A = attenuation; N = note
                    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
                    #  0  0 V2 V1 V0 A3 A2 A1 A0 N6 N5 N4 N3 N2 N1 N0
                    note = word & 0x7F
                    attenuation = (word & 0x780) >> 7
                    voice = (word & 0x3800) >> 11
                    self.__note_on(voice, note, attenuation)

                elif word & 0xC000 == 0x8000:
                    # delay: D = delay in milliseconds
                    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
                    #  1  0 DD DC DB DA D9 D8 D7 D6 D5 D4 D3 D2 D1 D0
                    ms = word & 0x3FFF
                    # TODO use utime.ticks_ms() et al to deduct busy time from sleep time and avoid song slowdowns
                    utime.sleep_ms(ms)

                elif word & 0xC000 == 0xC000:
                    # notes off: C = channel; V = voice mask
                    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
                    #  1  1  0  0  0  0  0  0 V7 V6 V5 V4 V3 V2 V1 V0
                    mask = word & 0xFF
                    self.__notes_off(mask)
            utime.sleep_ms(1000)
        finally:
            self.timer.deinit()
            self.__lights_off()
            self.sound.silence()

    def __init_frequency_table(self):
        self.frequency_table = array('H') # unsigned short
        n = Sound.CLOCK_FREQ / (32 * 440)
        for midi_note in range(128):
            f = n / math.pow(2, (midi_note - 69.0) / 12)
            while f > 1023:
                f /= 2  # shift notes that won't fit into the frequency register up an octave until they do
            self.frequency_table.append(round(f))

    def __init_leds(self):
        self.pwms = []
        for pin in MusicPlayer.LED_PINS:
            if pin == None:
                self.pwms.append(None)
            else:
                pwm = PWM(Pin(pin))
                pwm.freq(120)
                pwm.duty_u16(0)
                self.pwms.append(pwm)

    def __lights_off(self):
        for pwm in self.pwms:
            if pwm:
                pwm.duty_u16(0)

    def __set_led_intensity(self, voice, atten):
        if self.pwms[voice]:
            duty = 0xfff0 >> atten
            self.pwms[voice].duty_u16(duty)

    def __note_on(self, voice, note, attenuation):
        self.atten[voice] = attenuation
        self.target[voice] = min(attenuation + 3, 15)
        self.sound.set_frequency(voice, self.frequency_table[note])
        self.sound.set_attenuation(voice, self.atten[voice])
        self.__set_led_intensity(voice, self.atten[voice])

    def __notes_off(self, mask):
        for voice in range(8):
            if 0 != (mask & (1 << voice)):
                self.target[voice] = 15

    def __process_envelopes(self, _timer):
        for voice in range(8):
            if self.atten[voice] < self.target[voice]:
                self.atten[voice] += 1
                self.sound.set_attenuation(voice, self.atten[voice])
                self.__set_led_intensity(voice, self.atten[voice])

