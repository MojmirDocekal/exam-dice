# Exam Dice — random question picker

🎲 <https://mojmirdocekal.github.io/exam-dice/>

Pick exam/interview questions for students by rolling a dice. The dice defaults
to 6 sides; the number of sides can be set to anything from 2 to 30 (i.e. the
number of questions you have).

**Series without repeats** — within one series every number comes up at most
once. If the dice rolls a number that was already drawn, it re-rolls
automatically (and tells you why). "New series" makes all numbers available
again, e.g. for the next group of students.

## Web app (PC / Android / iOS)

Plain HTML + CSS + JavaScript, no build step, no dependencies.

- **Android (Chrome)**: menu → *Add to Home screen* → install as an app.
- **iPhone (Safari)**: Share → *Add to Home Screen*.
- Works **offline** once loaded (service worker), and the current series
  survives an accidental page reload.
- Big touch-friendly ROLL button, vibration feedback on Android, quiet
  tick/chime sounds with a mute toggle (🔊).
- Keyboard on PC: Space/Enter = roll, N = new series.

## Terminal / desktop version (Python)

`exam_dice.py` is a single-file, standard-library-only version with a terminal
UI and a tkinter window UI:

```bash
python exam_dice.py            # window if possible, else terminal
python exam_dice.py --cli      # terminal UI (SPACE roll, N new series, S sides, Q quit)
python exam_dice.py --gui      # window UI
python exam_dice.py -s 12      # start with a d12
python exam_dice.py --selftest
```

## Local preview of the web app

```bash
python3 -m http.server 8000
# open http://localhost:8000
```
