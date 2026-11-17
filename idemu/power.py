"""Host-side Evo power transitions; no vehicle connection or firmware patching."""
import collections
import math
import threading
import time


class EvoPower:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.RLock()
        self._mode = 'auto'
        self._return_mode = 'auto'
        self._deadline = None
        self._last_on = None
        self._auto_welcome = False
        self._duration = 10.0
        self._history = collections.deque(maxlen=24)

    def configure(self, config):
        auto = config.get('on_wake', self._auto_welcome)
        duration = config.get('duration', self._duration)
        if not isinstance(auto, bool):
            raise ValueError('on_wake must be a boolean')
        if isinstance(duration, bool):
            raise ValueError('duration must be between 1 and 60 seconds')
        try:
            duration = float(duration)
        except (ValueError, TypeError):
            raise ValueError('duration must be between 1 and 60 seconds')
        if not math.isfinite(duration) or not 1 <= duration <= 60:
            raise ValueError('duration must be between 1 and 60 seconds')
        with self._lock:
            self._auto_welcome, self._duration = auto, duration
            return self.config()

    def config(self):
        with self._lock:
            return {'on_wake': self._auto_welcome, 'duration': self._duration}

    def _change(self, mode, reason):
        self._mode = mode
        self._history.append({'time': round(self._clock(), 3), 'mode': mode, 'reason': reason})

    def _welcome(self, return_mode, reason):
        self._return_mode = return_mode
        self._deadline = self._clock() + self._duration
        self._change('welcome', reason)

    def action(self, action):
        with self._lock:
            if action == 'welcome':
                if self._mode == 'welcome':
                    raise ValueError('Welcome is already active; resume or wait before showing it again')
                self._welcome('awake' if self._mode == 'sleep' else self._mode, 'manual')
            elif action == 'sleep':
                self._deadline = None
                self._change('sleep', 'manual')
            elif action == 'wake':
                if self._auto_welcome and (self._mode == 'sleep' or self._last_on is False):
                    self._welcome('awake', 'sleep-to-wake')
                else:
                    self._deadline = None
                    self._change('awake', 'manual')
            elif action == 'auto':
                self._deadline = None
                self._change('auto', 'manual')
            else:
                raise ValueError('Unknown power action')

    def sample(self, ignition_on):
        with self._lock:
            ignition_on = bool(ignition_on)
            now = self._clock()
            if self._mode == 'welcome' and now >= self._deadline:
                self._deadline = None
                self._change(self._return_mode, 'welcome-finished')
            if self._mode == 'auto' and self._auto_welcome and self._last_on is False and ignition_on:
                self._welcome('auto', 'ignition-wake')
            self._last_on = ignition_on
            if self._mode == 'welcome':
                # Firmware maps Welcomescreen to coarse power mode 0, rather than user-on 3.
                coarse, detailed = 0, 0x5A
            elif self._mode == 'sleep' or (self._mode == 'auto' and not ignition_on):
                coarse, detailed = 0, 0
            else:
                coarse, detailed = 3, 0x63
            return {'mode': self._mode, 'power_state': coarse, 'power_state_detailed': detailed,
                    'remaining': round(max(0, self._deadline - now), 1) if self._deadline else 0,
                    **self.config(), 'history': list(self._history)}
