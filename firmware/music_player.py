import utime
from machine import Pin, PWM
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
    DYNAMICS = [(9, 14), (6, 12), (3, 10), (0, 8)]
    LED_PINS = [16, 17, 18, None, 19, 20, 21, None]
    def __init__(self):
        self.sound = Sound()
        self.atten = [15] * 8
        self.target = [15] * 8
        self.__init_leds()

    def play_song(self, filename):
        for word in read_words(filename):
            if word & 0x8000 == 0:
                # note on: C = channel; V = voice; D = dynamic; F = freq
                # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
                #  0 C0 V1 V0 D1 D0 F9 F8 F7 F6 F5 F4 F3 F2 F1 F0
                freq = word & 0x3FF
                dynamic = (word & 0xC00) >> 10
                voice = (word & 0x7000) >> 12
                print(freq)
                self.__note_on(voice, freq, dynamic)

            elif word & 0xC000 == 0x8000:
                # delay: D = delay in milliseconds
                # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
                #  1  0 DD DC DB DA D9 D8 D7 D6 D5 D4 D3 D2 D1 D0
                ms = word & 0x3FFF
                # TODO use utime.ticks_ms() et al to deduct busy time from sleep time and avoid song slowdowns
                utime.sleep_ms(ms)

            elif word & 0xC000 == 0xC000:
                # notes off: C = channel; L = left chip; R = right chip
                # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
                #  1  1  0  0  0  0  0  0 R3 R2 R1 R0 L3 L2 L1 L0
                mask = word & 0xFF
                self.__notes_off(mask)

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

    def __set_led_intensity(self, voice, atten):
        if self.pwms[voice]:
            duty = (15 - atten)
            duty = duty * duty * 288
            self.pwms[voice].duty_u16(duty)

    def __note_on(self, voice, frequency, dynamic):
        self.atten[voice] = MusicPlayer.DYNAMICS[dynamic][0]
        self.target[voice] = MusicPlayer.DYNAMICS[dynamic][1]
        self.sound.set_frequency(voice, frequency)
        self.sound.set_attenuation(voice, self.atten[voice])
        self.__set_led_intensity(voice, self.atten[voice])

    def __notes_off(self, mask):
        for voice in range(8):
            if 0 != (mask & (1 << voice)):
                self.target[voice] = 15
                # TODO remove the following lines after envelope is implemented
                self.atten[voice] = 15
                self.sound.set_attenuation(voice, 15)
                self.__set_led_intensity(voice, 15)

    def __process_envelopes(self):
        for voice in range(8):
            if self.atten[voice] < self.target[voice]:
                self.atten[voice] += 1
                self.sound.set_attenuation(voice, self.atten[voice])
                self.__set_led_intensity(voice, self.atten[voice])
