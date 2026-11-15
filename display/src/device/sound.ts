// One short tone at each step change (APP-413; 3C, "Motion and sound").
// Safari plays Web Audio only after a tap has created or resumed the
// audio context (A-49), so the first tap on the page unlocks it.

const TONE_HZ = 880;
const TONE_S = 0.15;
const ATTACK_S = 0.01;
const VOLUME = 0.25;

let context: AudioContext | null = null;

export function unlockSound(): void {
  if (typeof AudioContext === "undefined") {
    return;
  }
  context ??= new AudioContext();
  if (context.state === "suspended") {
    void context.resume();
  }
}

export function tone(): void {
  if (context === null || context.state !== "running") {
    return;
  }
  const start = context.currentTime;
  const oscillator = context.createOscillator();
  const gain = context.createGain();
  oscillator.frequency.value = TONE_HZ;
  gain.gain.setValueAtTime(0, start);
  gain.gain.linearRampToValueAtTime(VOLUME, start + ATTACK_S);
  gain.gain.linearRampToValueAtTime(0, start + TONE_S);
  oscillator.connect(gain).connect(context.destination);
  oscillator.start(start);
  oscillator.stop(start + TONE_S);
}
