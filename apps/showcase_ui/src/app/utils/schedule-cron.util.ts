/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

export type RepeatMode = 'daily' | 'weekdays' | 'weekends' | 'custom' | 'interval';

/** Everything the schedule picker collects. Days are cron day-of-week numbers, Sunday = 0. */
export interface ScheduleSpec {
  repeat: RepeatMode;
  days: number[];
  /** `HH:MM` strings, 24 hour. */
  times: string[];
  intervalMinutes: number;
  /** Inclusive hour window for the interval mode, or null for the whole day. */
  fromHour: number | null;
  toHour: number | null;
}

const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const TIME_RE = /^([01]\d|2[0-3]):([0-5]\d)$/;

const sortedUnique = (nums: number[]): number[] => [...new Set(nums)].sort((a, b) => a - b);

function dowField(days: number[]): string {
  const d = sortedUnique(days);
  if (d.length === 7) return '*';
  if (d.join() === '1,2,3,4,5') return '1-5';
  return d.join(',');
}

function specDays(spec: ScheduleSpec): number[] {
  if (spec.repeat === 'weekdays') return [1, 2, 3, 4, 5];
  if (spec.repeat === 'weekends') return [0, 6];
  if (spec.repeat === 'custom') return spec.days;
  return [0, 1, 2, 3, 4, 5, 6];
}

/** Why the spec cannot become a cron, or null when it can. */
export function validateSpec(spec: ScheduleSpec): string | null {
  if (spec.repeat === 'interval') {
    const n = spec.intervalMinutes;
    if (!Number.isInteger(n) || n < 5 || n > 720) return 'Interval must be a whole number from 5 to 720 minutes.';
    if (n < 60 && 60 % n !== 0) return 'Under an hour, pick a value that divides 60 evenly (5, 10, 12, 15, 20, 30).';
    if (n > 60 && n % 60 !== 0) return 'Over an hour, pick whole hours (60, 120, 180, ...).';
    const { fromHour: f, toHour: t } = spec;
    if ((f === null) !== (t === null)) return 'Set both the from and to hour, or neither.';
    if (f !== null && t !== null && (f < 0 || t > 23 || f > t)) return 'The from hour must not be after the to hour.';
    return null;
  }
  if (spec.repeat === 'custom' && spec.days.length === 0) return 'Pick at least one day.';
  if (spec.times.length === 0) return 'Add at least one time.';
  if (spec.times.some((t) => !TIME_RE.test(t))) return 'Fill in every time.';
  return null;
}

/** One cron per distinct minute: `09:00` + `18:00` share `0 9,18 * * *`, `18:30` gets its own. */
export function buildCrons(spec: ScheduleSpec): string[] {
  if (validateSpec(spec)) return [];
  if (spec.repeat === 'interval') {
    const n = spec.intervalMinutes;
    const hours = spec.fromHour === null ? '' : `${spec.fromHour}-${spec.toHour}`;
    if (n < 60) return [`*/${n} ${hours || '*'} * * *`];
    const step = n / 60;
    return [`0 ${hours ? `${hours}/${step}` : `*/${step}`} * * *`];
  }
  const hoursByMinute = new Map<number, number[]>();
  for (const t of new Set(spec.times)) {
    const [h, m] = t.split(':').map(Number);
    hoursByMinute.set(m, [...(hoursByMinute.get(m) ?? []), h]);
  }
  const dow = dowField(specDays(spec));
  return [...hoursByMinute.entries()]
    .sort(([a], [b]) => a - b)
    .map(([m, hours]) => `${m} ${sortedUnique(hours).join(',')} * * ${dow}`);
}

function joinList(items: string[]): string {
  return items.length < 2 ? items.join('') : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

const pad = (n: number): string => String(n).padStart(2, '0');

function daysPhrase(days: number[]): string {
  const d = sortedUnique(days);
  if (d.length === 7) return 'every day';
  if (d.join() === '1,2,3,4,5') return 'on weekdays';
  if (d.join() === '0,6') return 'on weekends';
  // Monday first, Sunday last, matching the chips.
  return `on ${[...d.filter((x) => x !== 0), ...d.filter((x) => x === 0)].map((x) => DAY_NAMES[x]).join(', ')}`;
}

function windowPhrase(from: number | null, to: number | null): string {
  return from === null || to === null ? '' : `, ${pad(from)}:00 to ${pad(to)}:59`;
}

export function summarizeSpec(spec: ScheduleSpec): string {
  if (validateSpec(spec)) return '';
  if (spec.repeat === 'interval') {
    const n = spec.intervalMinutes;
    const every = n % 60 === 0 ? (n === 60 ? 'every hour' : `every ${n / 60} hours`) : `every ${n} minutes`;
    return `Runs ${every}${windowPhrase(spec.fromHour, spec.toHour)}.`;
  }
  const times = joinList([...new Set(spec.times)].sort());
  return `Runs at ${times} ${daysPhrase(specDays(spec))}.`;
}

/** Expand `1-5`, `0,6`, `1,3` to numbers (7 folds to 0), or null for anything else. */
function parseNumList(field: string, max: number): number[] | null {
  const out: number[] = [];
  for (const part of field.split(',')) {
    const m = /^(\d+)(?:-(\d+))?$/.exec(part);
    if (!m) return null;
    const a = Number(m[1]);
    const b = m[2] === undefined ? a : Number(m[2]);
    if (a > b || b > max) return null;
    for (let i = a; i <= b; i++) out.push(i);
  }
  return out;
}

/** Plain-English reading of a cron, or null when it is not one of the common shapes. */
export function describeCron(cron: string): string | null {
  const f = cron.trim().split(/\s+/);
  if (f.length !== 5 || f[2] !== '*' || f[3] !== '*') return null;
  const [minute, hour, , , dowText] = f;
  let days = [0, 1, 2, 3, 4, 5, 6];
  if (dowText !== '*') {
    const parsed = parseNumList(dowText, 7);
    if (!parsed) return null;
    days = sortedUnique(parsed.map((d) => d % 7));
  }
  const when = daysPhrase(days);

  const stepMinutes = /^\*\/(\d+)$/.exec(minute);
  if (stepMinutes) {
    const win = /^(\d+)-(\d+)$/.exec(hour);
    if (hour !== '*' && !win) return null;
    return `Every ${stepMinutes[1]} minutes${win ? windowPhrase(Number(win[1]), Number(win[2])) : ''}, ${when}`;
  }
  if (!/^\d+$/.test(minute)) return null;
  const stepHours = /^(?:\*|(\d+)-(\d+))\/(\d+)$/.exec(hour);
  if (stepHours) {
    const n = Number(stepHours[3]);
    const every = n === 1 ? 'Every hour' : `Every ${n} hours`;
    const win = stepHours[1] === undefined ? '' : windowPhrase(Number(stepHours[1]), Number(stepHours[2]));
    return `${every}${win}, ${when}`;
  }
  const hours = parseNumList(hour, 23);
  if (!hours) return null;
  const times = sortedUnique(hours).map((h) => `${pad(h)}:${pad(Number(minute))}`);
  return `At ${joinList(times)}, ${when}`;
}
