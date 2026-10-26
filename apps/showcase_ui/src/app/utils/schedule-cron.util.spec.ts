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

import { buildCrons, describeCron, ScheduleSpec, summarizeSpec, validateSpec } from './schedule-cron.util';

const base: ScheduleSpec = {
  repeat: 'daily',
  days: [],
  times: ['09:00'],
  intervalMinutes: 30,
  fromHour: null,
  toHour: null
};

describe('schedule-cron.util', () => {
  describe('buildCrons', () => {
    it('maps weekdays at 09:00', () => {
      expect(buildCrons({ ...base, repeat: 'weekdays' })).toEqual(['0 9 * * 1-5']);
    });

    it('maps weekends and custom days with Sunday as 0', () => {
      expect(buildCrons({ ...base, repeat: 'weekends' })).toEqual(['0 9 * * 0,6']);
      expect(buildCrons({ ...base, repeat: 'custom', days: [5, 1, 3] })).toEqual(['0 9 * * 1,3,5']);
      expect(buildCrons({ ...base, repeat: 'custom', days: [0] })).toEqual(['0 9 * * 0']);
    });

    it('collapses all seven custom days and Mon-Fri the same way as the presets', () => {
      expect(buildCrons({ ...base, repeat: 'custom', days: [0, 1, 2, 3, 4, 5, 6] })).toEqual(['0 9 * * *']);
      expect(buildCrons({ ...base, repeat: 'custom', days: [5, 4, 3, 2, 1] })).toEqual(['0 9 * * 1-5']);
    });

    it('merges times that share a minute into one expression', () => {
      expect(buildCrons({ ...base, times: ['09:00', '18:00'] })).toEqual(['0 9,18 * * *']);
    });

    it('splits times with different minutes into separate expressions', () => {
      expect(buildCrons({ ...base, times: ['09:00', '18:30'] })).toEqual(['0 9 * * *', '30 18 * * *']);
    });

    it('ignores duplicate times', () => {
      expect(buildCrons({ ...base, times: ['09:00', '09:00'] })).toEqual(['0 9 * * *']);
    });

    it('builds interval crons with and without an hour window', () => {
      expect(buildCrons({ ...base, repeat: 'interval' })).toEqual(['*/30 * * * *']);
      expect(buildCrons({ ...base, repeat: 'interval', fromHour: 9, toHour: 17 })).toEqual(['*/30 9-17 * * *']);
      expect(buildCrons({ ...base, repeat: 'interval', intervalMinutes: 120 })).toEqual(['0 */2 * * *']);
      expect(buildCrons({ ...base, repeat: 'interval', intervalMinutes: 120, fromHour: 8, toHour: 20 })).toEqual([
        '0 8-20/2 * * *'
      ]);
    });

    it('returns nothing for an invalid spec', () => {
      expect(buildCrons({ ...base, times: [] })).toEqual([]);
      expect(buildCrons({ ...base, repeat: 'custom', days: [] })).toEqual([]);
    });
  });

  describe('validateSpec', () => {
    it('rejects intervals cron cannot express evenly', () => {
      expect(validateSpec({ ...base, repeat: 'interval', intervalMinutes: 4 })).toContain('5 to 720');
      expect(validateSpec({ ...base, repeat: 'interval', intervalMinutes: 7 })).toContain('divides 60');
      expect(validateSpec({ ...base, repeat: 'interval', intervalMinutes: 90 })).toContain('whole hours');
      expect(validateSpec({ ...base, repeat: 'interval', fromHour: 9, toHour: null })).toContain('both');
      expect(validateSpec({ ...base, repeat: 'interval', fromHour: 17, toHour: 9 })).toContain('from hour');
      expect(validateSpec({ ...base, repeat: 'interval', intervalMinutes: 15 })).toBeNull();
    });

    it('requires a complete time', () => {
      expect(validateSpec({ ...base, times: [''] })).toContain('every time');
    });
  });

  describe('summarizeSpec', () => {
    it('lists times and days', () => {
      expect(summarizeSpec({ ...base, repeat: 'custom', days: [1, 3, 5], times: ['18:30', '09:00'] })).toBe(
        'Runs at 09:00 and 18:30 on Mon, Wed, Fri.'
      );
      expect(summarizeSpec({ ...base, repeat: 'weekdays' })).toBe('Runs at 09:00 on weekdays.');
      expect(summarizeSpec({ ...base, repeat: 'custom', days: [0, 6] })).toBe('Runs at 09:00 on weekends.');
      expect(summarizeSpec({ ...base, repeat: 'custom', days: [0, 2] })).toBe('Runs at 09:00 on Tue, Sun.');
      expect(summarizeSpec({ ...base, times: ['08:00', '12:00', '18:00'] })).toBe(
        'Runs at 08:00, 12:00 and 18:00 every day.'
      );
    });

    it('describes intervals', () => {
      expect(summarizeSpec({ ...base, repeat: 'interval', fromHour: 9, toHour: 17 })).toBe(
        'Runs every 30 minutes, 09:00 to 17:59.'
      );
      expect(summarizeSpec({ ...base, repeat: 'interval', intervalMinutes: 60 })).toBe('Runs every hour.');
    });
  });

  describe('describeCron', () => {
    it('reads the shapes buildCrons emits', () => {
      expect(describeCron('0 9,18 * * 1-5')).toBe('At 09:00 and 18:00, on weekdays');
      expect(describeCron('30 7 * * 0,6')).toBe('At 07:30, on weekends');
      expect(describeCron('0 9 * * 1,3,5')).toBe('At 09:00, on Mon, Wed, Fri');
      expect(describeCron('0 9 * * 7')).toBe('At 09:00, on Sun');
      expect(describeCron('*/30 9-17 * * *')).toBe('Every 30 minutes, 09:00 to 17:59, every day');
      expect(describeCron('0 */2 * * *')).toBe('Every 2 hours, every day');
    });

    it('returns null for anything else', () => {
      expect(describeCron('0 9 15 * *')).toBeNull();
      expect(describeCron('0 9 * 1 *')).toBeNull();
      expect(describeCron('0 9')).toBeNull();
      expect(describeCron('0 9 * * MON')).toBeNull();
      expect(describeCron('*/5 */2 * * *')).toBeNull();
    });
  });
});
