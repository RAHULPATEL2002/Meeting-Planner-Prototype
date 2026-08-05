import {
  formatDuration,
  isoToLocalInput,
  localInputToIsoUtc,
  nextHalfHourLocalInput,
} from './datetime';

describe('datetime helpers', () => {
  describe('localInputToIsoUtc', () => {
    it('treats a datetime-local value as the browser’s local time', () => {
      const iso = localInputToIsoUtc('2026-08-10T09:00');
      // We cannot assert an absolute UTC string without pinning the test
      // machine's timezone, so assert the *relationship* instead: converting
      // back must give the same wall-clock time the user typed.
      expect(isoToLocalInput(iso)).toBe('2026-08-10T09:00');
    });

    it('produces an instant the API can parse unambiguously', () => {
      expect(localInputToIsoUtc('2026-08-10T09:00')).toMatch(
        /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/,
      );
    });

    it('round-trips a value that crosses midnight in UTC', () => {
      expect(isoToLocalInput(localInputToIsoUtc('2026-12-31T23:45'))).toBe('2026-12-31T23:45');
    });
  });

  describe('isoToLocalInput', () => {
    it('zero-pads single-digit months, days, hours and minutes', () => {
      const iso = localInputToIsoUtc('2026-01-02T03:04');
      expect(isoToLocalInput(iso)).toBe('2026-01-02T03:04');
    });
  });

  describe('nextHalfHourLocalInput', () => {
    it('always lands on :00 or :30', () => {
      expect(nextHalfHourLocalInput()).toMatch(/T\d{2}:(00|30)$/);
    });

    it('offsets from that rounded slot', () => {
      const start = nextHalfHourLocalInput(0);
      const later = nextHalfHourLocalInput(60);
      const gap = new Date(later).getTime() - new Date(start).getTime();
      expect(gap).toBe(60 * 60 * 1000);
    });
  });

  describe('formatDuration', () => {
    it('shows minutes below an hour', () => {
      expect(formatDuration(45)).toBe('45m');
      expect(formatDuration(5)).toBe('5m');
    });

    it('shows a whole hour without a stray "0m"', () => {
      expect(formatDuration(60)).toBe('1h');
      expect(formatDuration(120)).toBe('2h');
    });

    it('combines hours and minutes', () => {
      expect(formatDuration(90)).toBe('1h 30m');
    });

    it('rolls over into days', () => {
      expect(formatDuration(24 * 60)).toBe('1d');
      expect(formatDuration(24 * 60 + 150)).toBe('1d 2h 30m');
    });
  });
});
