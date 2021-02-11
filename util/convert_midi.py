# this needs to match the value in firmware/sound.py
CLOCK_FREQ = 1_200_000

from argparse import ArgumentParser
from mido import MidiFile
import math

parser = ArgumentParser(description='Convert MIDI file for pico_player')
parser.add_argument('infile', type=str, help='input midi file')
parser.add_argument('-x', '--exclude-channels', type=int, metavar='CHANNEL', nargs='*',
                    help='exclude channels from the output file')
parser.add_argument('outfile', type=str, help='output binary file')
args = parser.parse_args()

class Note:
    def __init__(self, midi_note, channel, velocity):
        self.midi_note = midi_note
        self.channel = channel
        self.velocity = velocity

class Event:
    def __init__(self, delay = 0):
        self.delay = delay
        self.notes = {} # organized by midi note

    def add_note(self, note):
        # since all our voices sound the same, there is no point in adding the same midi note twice
        # just make it louder, using this extremely not-hokey velocity addition :P
        if note.midi_note in self.notes:
            self.notes[note.midi_note].velocity = min(127, self.notes[note.midi_note].velocity + note.velocity)
        else:
            self.notes[note.midi_note] = note

class Encoder:
    def __init__(self, included_channels):
        self.events = []
        self.included_channels = included_channels
        self.__build_preferred_chip_map()

    def log_delay(self, delay):
        if self.events and not self.events[-1].notes:
            self.events[-1].delay += delay
        else:
            self.events.append(Event(delay))

    def log_note(self, midi_note, channel, velocity):
        if channel == 10:
            return  # TODO: map percussion to noise channels
        if not channel in self.included_channels:
            return
        self.__ensure_event()
        self.events[-1].add_note(Note(midi_note, channel, velocity))

    def write_output(self, outfile):
        self.outfile = open(outfile, 'wb')
        for event in self.events:
            self.__write_event(event)
        self.outfile.close()

    def __ensure_event(self):
        if not self.events:
            self.events.append(Event(0))

    def __build_preferred_chip_map(self):
        c = 1
        self.preferred_chip = {}
        for ch in self.included_channels:
            self.preferred_chip[ch] = c
            c ^= 1

    def __assign_chip(self, notes):
        # set the preferred chip for the channel, then,
        # if more than 3 notes land on the same chip, flip some of them
        counts = [0, 0]
        for note in notes:
            note.chip = self.preferred_chip[note.channel]
            counts[note.chip] += 1

        flip_count = 0
        for i in range(2):
            if counts[i] > 3:
                flip_count = counts[i] - 3
                flip_val = i
                break

        for note in notes:
            if flip_count == 0:
                return
            if note.chip == flip_val:
                note.chip ^= 1
                flip_count -= 1

    def __write_event(self, event):
        self.__write_delay(event.delay)

        if len(event.notes) <= 6:
            notes = event.notes.values()
        else:
            # we're going to have to drop some notes
            # first, organize notes by channel
            notes_by_channel = {}
            for note in event.notes.values():
                if not note.channel in notes_by_channel:
                    notes_by_channel[note.channel] = []
                notes_by_channel[note.channel].append(note)

            # select the top note from each channel until we've got 6 notes
            notes = []
            while len(notes) < 6:
                for channel in notes_by_channel:
                    remaining_notes_in_channel = notes_by_channel[channel]
                    if remaining_notes_in_channel:
                        notes.append(remaining_notes_in_channel.pop())
                        if len(notes) == 6:
                            break

        self.__assign_chip(notes)
        for note in notes:
            self.__write_note(note.chip, note.midi_note, note.velocity)

    # shift notes up an octave if they would otherwise overflow the frequency register
    def __remap_note_if_necessary(self, note):
        while self.__midi_note_to_frequency(note) >= 1024:
            note += 12
        return note

    def __midi_note_to_frequency(self, midi_note):
        return round(CLOCK_FREQ / (32 * 440.0 * math.pow(2, (midi_note - 69.0) / 12)))

    def __midi_velocity_to_attenuation(self, velocity):
        return 15 - int(velocity / 8)

    # note: C = chip; A = attenuation; F = freq
    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
    #  0 C0 A3 A2 A1 A0 F9 F8 F7 F6 F5 F4 F3 F2 F1 F0
    def __write_note(self, chip, note, velocity):
        note = self.__remap_note_if_necessary(note)
        frequency = self.__midi_note_to_frequency(note)
        attenuation = self.__midi_velocity_to_attenuation(velocity)
        u16 = (chip & 1) << 14
        u16 |= (attenuation & 0xF) << 10
        u16 |= (frequency & 0x3FF)
        self.__write16(u16)

    # delay: D = delay in milliseconds
    # 15 14 13 12 11 10  9  8  7  6  5  4  3  2  1  0
    #  1  0 DD DC DB DA D9 D8 D7 D6 D5 D4 D3 D2 D1 D0
    def __write_delay(self, delay):
        delay = round(delay * 1000)
        while delay > 0x3FFF:
            self.__write16(0xBFFF)
            delay -= 0x3FFF
        if delay > 0:
            self.__write16(0x8000 | delay)

    def __write16(self, u16):
        self.outfile.write(u16.to_bytes(2, byteorder='big', signed=False))


midi = MidiFile(args.infile)

# NOTE: 1 is added to channels to match user-visible channel numbers in e.g. MuseScore

# I feel like there should be a better way to enumerate channels, but whatevs...
included_channels = set()
for msg in midi:
    if msg.type == 'note_on':
        included_channels.add(msg.channel + 1)

if args.exclude_channels:
    for c in args.exclude_channels:
        included_channels.discard(c)

encoder = Encoder(included_channels)
for msg in midi:
    if msg.time > 0:
        encoder.log_delay(msg.time)
    if not msg.is_meta:
        if msg.type == 'note_on' and msg.velocity > 0:
            encoder.log_note(msg.note, msg.channel + 1, msg.velocity)
encoder.write_output(args.outfile)
