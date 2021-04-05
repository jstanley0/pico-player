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
    LED_PINS = [16, 17, 18, 15, 19, 20, 21, 22]
    def __init__(self):
        self.sound = Sound()
        self._init_frequency_table()
        self.atten = [15] * 8
        self.target = [15] * 8
        self.decay_mask = [3] * 8
        self.decay_clock = 0
        self._init_leds()
        self.timer = Timer()

    def play_song(self, filename):
        try:
            self.timer.init(freq=80, mode=Timer.PERIODIC, callback=self._process_envelopes)
            for word in read_words(filename):
                cmd = (word >> 14) & 0x3
                if cmd == 0:
                    # note on: V = voice; A = attenuation; N = note
                    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
                    #  0  0 V2 V1 V0 A3 A2 A1 A0 N6 N5 N4 N3 N2 N1 N0
                    note = word & 0x7F
                    attenuation = (word & 0x780) >> 7
                    voice = (word & 0x3800) >> 11
                    self._note_on(voice, note, attenuation)

                elif cmd == 1:
                    # noise on: V = voice; A = attenuation; S = sustain; N = noise type
                    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
                    #  0  1  0  0  0 V0 S2 S1 S0 A3 A2 A1 A0 N2 N1 N0
                    noise = (word & 0b111)
                    atten = (word & 0b1111000) >> 3
                    sustain = (word & 0b1110000000) >> 7
                    voice = (word & 0b10000000000) >> 10
                    voice = 3 + (voice * 4)
                    self._noise_on(voice, noise, sustain, atten)

                elif cmd == 2:
                    # delay: D = delay in milliseconds
                    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
                    #  1  0 DD DC DB DA D9 D8 D7 D6 D5 D4 D3 D2 D1 D0
                    ms = word & 0x3FFF
                    # TODO use utime.ticks_ms() et al to deduct busy time from sleep time and avoid song slowdowns
                    utime.sleep_ms(ms)

                else:
                    # notes off: C = channel; V = voice mask
                    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
                    #  1  1  0  0  0  0  0  0 V7 V6 V5 V4 V3 V2 V1 V0
                    mask = word & 0xFF
                    self._notes_off(mask)
            utime.sleep_ms(1000)
        finally:
            self.timer.deinit()
            self._lights_off()
            self.sound.silence()

    def _init_frequency_table(self):
        self.frequency_table = array('H') # unsigned short
        n = Sound.CLOCK_FREQ / (32 * 440)
        for midi_note in range(128):
            f = n / math.pow(2, (midi_note - 69.0) / 12)
            while f > 1023:
                f /= 2  # shift notes that won't fit into the frequency register up an octave until they do
            self.frequency_table.append(round(f))

    def _init_leds(self):
        self.pwms = []
        for pin in MusicPlayer.LED_PINS:
            if pin == None:
                self.pwms.append(None)
            else:
                pwm = PWM(Pin(pin))
                pwm.freq(120)
                pwm.duty_u16(0)
                self.pwms.append(pwm)

    def _lights_off(self):
        for pwm in self.pwms:
            if pwm:
                pwm.duty_u16(0)

    def _set_led_intensity(self, voice, atten):
        if self.pwms[voice]:
            duty = 0xfff0 >> atten
            self.pwms[voice].duty_u16(duty)

    def _note_on(self, voice, note, attenuation):
        self.atten[voice] = attenuation
        self.target[voice] = min(attenuation + 3, 15)
        self.sound.set_frequency(voice, self.frequency_table[note])
        self.sound.set_attenuation(voice, attenuation)
        self._set_led_intensity(voice, attenuation)

    def _noise_on(self, voice, noise, sustain, attenuation):
        self.atten[voice] = attenuation
        self.target[voice] = 15
        self.decay_mask[voice] = sustain
        self.sound.set_noise(voice, noise)
        self.sound.set_attenuation(voice, attenuation)
        self._set_led_intensity(voice, attenuation)

    def _notes_off(self, mask):
        for voice in range(8):
            if 0 != (mask & (1 << voice)):
                self.target[voice] = 15

    def _process_envelopes(self, _timer):
        self.decay_clock = (self.decay_clock + 1) & 7
        for voice in range(8):
            if (self.decay_mask[voice] & self.decay_clock) == 0:
                if self.atten[voice] < self.target[voice]:
                    self.atten[voice] += 1
                    self.sound.set_attenuation(voice, self.atten[voice])
                    self._set_led_intensity(voice, self.atten[voice])



