import { EXERCISES, type Pose } from '../guides/StrengthGuide'

/**
 * R17 §1: stick-figure poses for the recovery routine, drawn with the Guides `Figure`
 * (same 120×90 grid, ground at y=84). The hip-flexor pose is the Strength guide's own.
 * Keys follow the backend's `figure` names; anything unknown falls back by keyword.
 */
const hipflexor = EXERCISES.find((e) => e.key === 'hipflexor')?.pose

const walk: Pose = {
  head: [60, 12],
  limbs: [[[60, 19], [60, 48]], [[60, 48], [68, 65], [73, 82]], [[60, 25], [67, 36], [72, 44]]],
  back: [[[60, 48], [54, 65], [47, 82]], [[60, 25], [53, 36], [49, 44]]],
  focus: [62, 64],
}

export const POSES: Record<string, Pose> = {
  walk,
  calf: {
    head: [86, 18], wall: 102,
    limbs: [[[83, 24], [66, 50]], [[66, 50], [44, 80], [36, 82]], [[80, 29], [92, 31], [101, 25]]],
    back: [[[66, 50], [79, 66], [82, 82]]],
    focus: [50, 72],
  },
  hamstring: {
    head: [40, 28],
    limbs: [[[46, 32], [68, 50]], [[68, 50], [52, 66], [38, 80], [36, 73]], [[50, 36], [48, 50], [48, 60]]],
    back: [[[68, 50], [76, 66], [74, 82]]],
    focus: [53, 64],
  },
  quad: {
    head: [60, 12],
    limbs: [[[60, 19], [60, 48]], [[60, 48], [60, 66], [62, 82]], [[60, 25], [54, 40], [50, 55]]],
    back: [[[60, 48], [58, 66], [48, 56]], [[60, 25], [72, 34], [80, 30]]],
    focus: [59, 57],
  },
  hip_flexor: hipflexor ?? walk,
  glute: {
    head: [16, 75],
    limbs: [[[23, 78], [56, 78]], [[56, 78], [74, 56], [86, 82]], [[28, 77], [48, 64], [64, 60]]],
    back: [[[56, 77], [64, 60], [82, 57]]],
    focus: [60, 70],
  },
  it_band: {
    head: [50, 14],
    limbs: [[[54, 20], [60, 48]], [[60, 48], [66, 66], [57, 82]], [[56, 25], [45, 13], [35, 10]]],
    back: [[[60, 48], [54, 66], [65, 82]], [[57, 26], [64, 36], [66, 44]]],
    focus: [64, 52],
  },
  adductor: {
    head: [50, 20],
    limbs: [[[50, 27], [52, 52]], [[52, 52], [38, 66], [36, 82]], [[52, 52], [78, 68], [100, 82]], [[51, 33], [42, 48], [40, 60]]],
    focus: [70, 63],
  },
  lower_back: {
    head: [22, 74],
    limbs: [[[29, 77], [62, 78]], [[62, 78], [48, 56], [64, 52]], [[33, 76], [46, 60], [53, 56]]],
    back: [[[62, 77], [52, 58], [68, 55]]],
    focus: [44, 77],
  },
  calf_roll: {
    head: [24, 40], roller: [72, 78],
    limbs: [[[26, 47], [40, 72]], [[40, 72], [70, 71], [98, 76]], [[28, 52], [20, 66], [18, 82]]],
    focus: [78, 72],
  },
  hamstring_roll: {
    head: [24, 40], roller: [54, 78],
    limbs: [[[26, 47], [40, 72]], [[40, 72], [70, 71], [98, 78]], [[28, 52], [20, 66], [18, 82]]],
    focus: [56, 71],
  },
  quad_roll: {
    head: [18, 58], roller: [66, 78],
    limbs: [[[24, 62], [56, 68]], [[56, 68], [102, 77]], [[26, 64], [26, 82], [38, 82]]],
    focus: [68, 71],
  },
  it_band_roll: {
    head: [20, 52], roller: [74, 79],
    limbs: [[[26, 58], [60, 70]], [[60, 70], [104, 80]], [[28, 58], [28, 82]]],
    focus: [74, 73],
  },
  glute_roll: {
    head: [44, 24], roller: [52, 78],
    limbs: [[[46, 31], [52, 66]], [[52, 66], [72, 64], [74, 82]], [[47, 38], [36, 56], [34, 82]]],
    back: [[[52, 66], [70, 56], [60, 52]]],
    focus: [52, 67],
  },
}

const ALIASES: Array<[RegExp, string]> = [
  [/roll/i, ''],
  [/calf|soleus|achilles/i, 'calf'],
  [/ham/i, 'hamstring'],
  [/quad/i, 'quad'],
  [/hip.?flex|lunge/i, 'hip_flexor'],
  [/glute|piriformis|figure/i, 'glute'],
  [/it.?band|itb|hip|tfl/i, 'it_band'],
  [/adduct|groin|butterfly/i, 'adductor'],
  [/back|knee.?to.?chest|child/i, 'lower_back'],
  [/walk|cool/i, 'walk'],
]

/** The pose for a step's `figure` (or `key`); never undefined. */
export function poseFor(figure: string | null | undefined, key?: string | null): Pose {
  for (const name of [figure, key]) {
    if (!name) continue
    const k = name.toLowerCase().replace(/[-\s]/g, '_')
    if (POSES[k]) return POSES[k]
    const roll = /roll|foam/.test(k)
    for (const [re, base] of ALIASES.slice(1)) {
      if (re.test(k)) return (roll && POSES[`${base}_roll`]) || POSES[base]
    }
  }
  return walk
}
