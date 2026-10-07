/**
 * Plain-English meaning of every Health number, in one place. Shown by the (i) buttons
 * on tiles and chart headers (InfoButton). 2–4 short sentences, no jargon.
 */

export type GlossaryEntry = {
  title: string
  /** What it is. */
  what: string
  /** Why it matters for running. */
  why: string
  /** Which way is better, in words. */
  better: string
}

export const GLOSSARY = {
  readiness: {
    title: 'Readiness',
    what: 'A 0–100 score for how ready your body is to train today, from sleep, HRV, recent load and stress.',
    why: 'On a low day an easy run is the right run. It never means “go harder” on a high day.',
    better: 'Higher is better. Under 40 means keep it very easy or rest.',
  },
  hrv: {
    title: 'HRV (heart-rate variability)',
    what: 'The tiny changes in time between heartbeats, measured overnight by your watch.',
    why: 'It shows how rested your body is. A low reading for several nights means you’re not recovering well — keep runs easy.',
    better: 'Higher than your usual is better. Staying inside your normal band is fine.',
  },
  rhr: {
    title: 'Resting heart rate',
    what: 'Your heart rate when you’re completely still, mostly measured while you sleep.',
    why: 'As you get fitter, your heart pumps more per beat, so this slowly drops. A sudden jump of 5+ can mean tiredness or illness.',
    better: 'Lower is better (slowly, over weeks).',
  },
  stress: {
    title: 'Stress',
    what: 'Garmin’s 0–100 score of how hard your body is working when you’re not exercising, from your heart rhythm.',
    why: 'Work, worry, poor sleep and alcohol all count. A stressed body recovers more slowly from runs.',
    better: 'Lower is better. 0–25 is resting, above 50 is stressful.',
  },
  body_battery: {
    title: 'Body Battery',
    what: 'Garmin’s 0–100 estimate of your energy. Sleep and rest charge it; activity and stress drain it.',
    why: 'Starting a run with a high battery usually means it will feel easier.',
    better: 'Higher is better, especially when you wake up.',
  },
  vo2max: {
    title: 'VO2max',
    what: 'An estimate of how much oxygen your body can use at full effort. Garmin works it out from your runs with heart rate.',
    why: 'It’s the size of your aerobic “engine”. It goes up slowly with regular easy running.',
    better: 'Higher is better. It moves over months, not days.',
  },
  sleep: {
    title: 'Sleep time',
    what: 'How long you were actually asleep, not just in bed.',
    why: 'Your body repairs itself and gets fitter while you sleep. Short nights make every run harder.',
    better: 'More is better, up to what you need (usually 7–9 hours).',
  },
  sleep_score: {
    title: 'Sleep score',
    what: 'Garmin’s 0–100 grade for a night, from how long you slept, how deep it was and how restless you were.',
    why: 'A quick way to see whether last night helped you recover.',
    better: 'Higher is better. 80+ is good, under 60 is poor.',
  },
  deep_sleep: {
    title: 'Deep sleep',
    what: 'The deepest stage of sleep, mostly early in the night.',
    why: 'This is when your muscles repair the most. Alcohol and late meals cut it short.',
    better: 'More is better.',
  },
  regularity: {
    title: 'Bedtime regularity',
    what: 'How much your bedtime moves around from night to night (±minutes).',
    why: 'Going to bed at the same time helps you fall asleep faster and sleep deeper.',
    better: 'Smaller is better. Under ±30 min is very regular.',
  },
  restless: {
    title: 'Restless moments',
    what: 'How many times your watch felt you move a lot during the night.',
    why: 'Lots of tossing and turning usually means lighter, less refreshing sleep.',
    better: 'Fewer is better.',
  },
  breathing_rate: {
    title: 'Breathing rate',
    what: 'Breaths per minute while you sleep.',
    why: 'It stays very steady for each person. A rise above your usual can be an early sign of illness — run easy only.',
    better: 'Steady at your normal is best. Up is a warning sign.',
  },
  spo2: {
    title: 'SpO2 (blood oxygen)',
    what: 'How full of oxygen your blood is, measured by your watch while you sleep.',
    why: 'Most people sit at 95–99%. Lower values can come with illness, altitude or breathing problems at night.',
    better: 'Higher is better. Talk to a doctor if it’s often under 90%.',
  },
  endurance_score: {
    title: 'Endurance score',
    what: 'Garmin’s number for how long you can keep going, from all your recent training.',
    why: 'It grows with regular, mostly easy running and longer outings.',
    better: 'Higher is better.',
  },
  fitness_age: {
    title: 'Fitness age',
    what: 'The age your fitness matches, from your VO2max, resting heart rate and activity.',
    why: 'A friendly way to see progress — regular running pulls it down.',
    better: 'Lower is better.',
  },
  lactate_threshold: {
    title: 'Lactate threshold',
    what: 'The hardest effort you can hold for about an hour before your legs “burn”. Garmin estimates it as a heart rate and a pace.',
    why: 'Your training zones are worked out from it, so easy runs really stay easy.',
    better: 'A faster pace at the same heart rate is better.',
  },
  run_fraction: {
    title: 'Running share',
    what: 'How much of each outing you spent running rather than walking.',
    why: 'While you build up with run/walk, this is the clearest sign of progress.',
    better: 'Higher is better — slowly.',
  },
  longest_run: {
    title: 'Longest continuous run',
    what: 'The longest stretch you ran without a walk break.',
    why: 'It shows your running stamina. Adding 30–60 seconds at a time is plenty.',
    better: 'Longer is better.',
  },
  easy_pace: {
    title: 'Easy-pace efficiency',
    what: 'Your pace while your heart rate is in the easy zone (Zone 2).',
    why: 'Going faster at the same easy effort means your aerobic fitness is improving.',
    better: 'Faster is better (a lower number per km).',
  },
  cadence: {
    title: 'Cadence',
    what: 'Steps per minute while running.',
    why: 'Shorter, quicker steps land under your hips and are easier on knees and shins.',
    better: 'Around 160–175 suits most runners. Raise it a little at a time.',
  },
  ground_contact: {
    title: 'Ground contact time',
    what: 'How long each foot stays on the ground per step, in milliseconds.',
    why: 'Shorter contact usually means a lighter, springier stride.',
    better: 'Lower is better.',
  },
  vertical_oscillation: {
    title: 'Vertical oscillation (bounce)',
    what: 'How much you bounce up and down with each step, in centimetres.',
    why: 'Bouncing a lot spends energy going up instead of forward.',
    better: 'Lower is better.',
  },
  stride_length: {
    title: 'Stride length',
    what: 'How far you travel with each step.',
    why: 'It grows naturally as you get fitter and faster. Forcing longer steps causes overstriding.',
    better: 'Neither — don’t chase it directly.',
  },
  steps: {
    title: 'Steps',
    what: 'Every step your watch counted today, runs included.',
    why: 'Moving through the day helps recovery and overall health, not just training.',
    better: 'More is better. Your goal adapts to your usual days.',
  },
  active_min: {
    title: 'Active minutes',
    what: 'Minutes you spent moving — walking, running or anything that gets you up.',
    why: 'Regular movement keeps your body loose and helps easy recovery.',
    better: 'More is better.',
  },
  sedentary_min: {
    title: 'Sitting time',
    what: 'Minutes you spent still while awake.',
    why: 'Long still stretches make you stiff. Short walks break them up.',
    better: 'Less is better.',
  },
  stress_high_min: {
    title: 'High-stress time',
    what: 'Minutes in Garmin’s highest stress band (76–100) while not exercising.',
    why: 'Lots of high-stress time often shows up as worse sleep and lower HRV that night.',
    better: 'Less is better.',
  },
  awake_hr: {
    title: 'Heart rate while awake',
    what: 'Your average heart rate during the day, not counting sleep and workouts.',
    why: 'A slow drift down over weeks is a sign of fitness. A jump can mean stress or illness.',
    better: 'Lower is better (over weeks).',
  },
  bb_bedtime: {
    title: 'Body Battery at bedtime',
    what: 'How much energy you had left when you went to bed.',
    why: 'Going to bed with more left usually means a calmer day and better recovery.',
    better: 'Higher is better.',
  },
  race_predictions: {
    title: 'Race predictions',
    what: 'Garmin’s guess at what you could run today if you raced each distance all-out.',
    why: 'Handy to watch fitness change. They’re optimistic for long races until you’ve trained for them.',
    better: 'Faster is better.',
  },
  acute_load: {
    title: 'Training load',
    what: 'How much training you’ve done recently, adding up how long and how hard each session was.',
    why: 'Load that rises slowly builds fitness. Big jumps raise the risk of injury.',
    better: 'Steady, gradual rises are best.',
  },
  // --- R13 ---------------------------------------------------------------------------
  injury_risk: {
    title: 'Injury watch',
    what: 'A daily check of the patterns that often come before running injuries: mileage jumping too fast, one very long run, your step rate dropping, uneven ground contact, worn-out shoes and pain you report.',
    why: 'Most running injuries come from doing too much too soon. Spotting it early means a few easier days instead of weeks off.',
    better: 'Low is what you want. Moderate means ease off a little; high means keep it very easy or rest. It is not a diagnosis — see a physio if pain persists.',
  },
  ramp: {
    title: 'Weekly ramp',
    what: 'How much more you ran this week than the weeks before. The acute:chronic ratio (ACWR) compares the last 7 days with the last 4 weeks.',
    why: 'Tissues adapt slower than fitness. Jumps of more than about 10 % a week, or an ACWR above 1.3, raise injury risk.',
    better: 'Small, steady rises. An ACWR between 0.8 and 1.3 is the sweet spot.',
  },
  long_run_share: {
    title: 'Long-run share',
    what: 'The share of your week’s distance that came from your single longest run.',
    why: 'When one run is a big chunk of the week, that run carries most of the strain.',
    better: 'Under about 40 % of the week.',
  },
  gct_balance: {
    title: 'Ground-contact balance',
    what: 'How evenly your left and right feet share time on the ground, from a Garmin chest strap or running pod. 50/50 is perfectly even.',
    why: 'A lopsided stride can be an early sign you’re protecting a sore spot.',
    better: 'Close to 50/50. More than 2 % off for several runs is worth noticing.',
  },
  pain_severity: {
    title: 'Pain level',
    what: '1 = a niggle you notice but that doesn’t change how you move. 2 = sore, it changes how you move a little. 3 = it hurts — you’d stop or limp.',
    why: 'Sore on the same spot two days running is the signal to ease off before it becomes an injury.',
    better: 'None, of course. If something stays at 2 or more, or gets worse, see a physio.',
  },
  mood: {
    title: 'Mood',
    what: 'How you feel today, from 1 (low) to 5 (great). One tap a day.',
    why: 'Mood follows sleep, stress and training. Over weeks it shows what lifts you — and when to keep runs gentle.',
    better: 'Higher is better. One low day means nothing; a low run of days is worth an easier week.',
  },
  energy: {
    title: 'Energy',
    what: 'How much energy you have today, from 1 (drained) to 5 (full of energy).',
    why: 'Low energy for several days, especially with poor sleep, is a sign to recover rather than push.',
    better: 'Higher is better. It doesn’t mean “train harder” on a high day.',
  },
  caffeine_late: {
    title: 'Late caffeine',
    what: 'Coffee, tea or energy drinks after 14:00. Caffeine stays in your body for 5–6 hours or more.',
    why: 'It can make it harder to fall asleep and cut deep sleep, which is when your body repairs from training.',
    better: 'Fewer late cups. Morning coffee is fine and can even help a run.',
  },
  cravings_resisted: {
    title: 'Cravings resisted',
    what: 'Of the cravings you logged, the share where you didn’t smoke.',
    why: 'Every craving you ride out makes the next one weaker. Most pass within 3–5 minutes.',
    better: 'Higher is better. A slip isn’t failure — log it and keep going.',
  },
  hr_at_pace: {
    title: 'HR at pace',
    what: 'Your heart rate at a given running pace.',
    why: 'As your aerobic fitness grows, the same pace costs fewer beats. Heat, poor sleep and illness push it up.',
    better: 'Lower than usual at the same pace is better.',
  },
  hr_drift: {
    title: 'HR drift',
    what: 'How much your heart rate creeps up from the first half to the second half of a steady run.',
    why: 'A big drift means the run got harder than planned — heat, dehydration or starting too fast.',
    better: 'Lower is better. Under 5 % is a well-paced easy run.',
  },
} satisfies Record<string, GlossaryEntry>

export type GlossaryKey = keyof typeof GLOSSARY

/** Training status words (Garmin) → plain English, for the status pill sheet. */
export const STATUS_MEANING: Array<{ key: string; label: string; text: string }> = [
  { key: 'productive', label: 'Productive', text: 'Your fitness is improving with your current training.' },
  { key: 'maintaining', label: 'Maintaining', text: 'Your fitness is holding steady.' },
  { key: 'recovery', label: 'Recovery', text: 'Lighter training lately, so your body is catching up.' },
  { key: 'unproductive', label: 'Unproductive', text: 'You’re training enough, but fitness isn’t improving — often a sign of poor sleep or high stress.' },
  { key: 'detraining', label: 'Detraining', text: 'Too little training lately, so fitness is starting to slip.' },
  { key: 'overreaching', label: 'Overreaching', text: 'Too much training for now. Rest more and keep runs easy.' },
  { key: 'strained', label: 'Strained', text: 'Your body is struggling to recover. Rest and easy days come first.' },
  { key: 'peaking', label: 'Peaking', text: 'You’re fresh and race-ready.' },
  { key: 'no_status', label: 'No status', text: 'Garmin needs more runs with heart rate before it can say.' },
]

/** The three load-focus bars. */
export const LOAD_FOCUS_MEANING: Record<string, string> = {
  low_aerobic: 'Easy running (Zones 1–2). Builds your endurance base.',
  high_aerobic: 'Steady/tempo efforts (Zones 3–4). Raises the pace you can hold.',
  anaerobic: 'Short hard bursts (Zone 5, strides/intervals). Builds top-end speed.',
}
