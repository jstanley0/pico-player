import utime
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
        self.atten = [15] * 8
        self.__init_leds()
        self.timer = Timer()

    def play_song(self, filename):
        try:
            self.timer.init(freq=20, mode=Timer.PERIODIC, callback=self.__process_envelopes)
            for word in read_words(filename):
                if word & 0x8000 == 0:
                    # note: C = chip; A = attenuation; F = freq
                    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
                    #  0 C0 A3 A2 A1 A0 F9 F8 F7 F6 F5 F4 F3 F2 F1 F0
                    chip = (word & 0x4000) >> 14
                    atten = (word & 0x3C00) >> 10
                    freq = word & 0x3FF
                    self.__note(chip, freq, atten)

                elif word & 0xC000 == 0x8000:
                    # delay: D = delay in milliseconds
                    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
                    #  1  0 DD DC DB DA D9 D8 D7 D6 D5 D4 D3 D2 D1 D0
                    ms = word & 0x3FFF
                    # TODO use utime.ticks_ms() et al to deduct busy time from sleep time and avoid song slowdowns
                    utime.sleep_ms(ms)
        finally:
            self.timer.deinit()
            self.__lights_off()
            self.sound.silence()

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
            duty = (15 - atten)
            duty = duty * duty * duty * duty
            self.pwms[voice].duty_u16(duty)

    def __note(self, chip, frequency, attenuation):
        if chip == 0:
            voice = 0
            for i in range(1, 3):
                if self.atten[i] > self.atten[voice]:
                    voice = i
        else:
            voice = 6
            for i in range(5, 3, -1):
                if self.atten[i] > self.atten[voice]:
                    voice = i
        self.atten[voice] = attenuation
        self.sound.set_frequency(voice, frequency)
        self.sound.set_attenuation(voice, self.atten[voice])
        self.__set_led_intensity(voice, self.atten[voice])

    def __process_envelopes(self, _timer):
        for voice in range(8):
            if self.atten[voice] < 15:
                self.atten[voice] += 1
                self.sound.set_attenuation(voice, self.atten[voice])
                self.__set_led_intensity(voice, self.atten[voice])

