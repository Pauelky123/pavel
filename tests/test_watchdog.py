import subprocess
import sys
import time
import unittest
from arena.watchdog import Watchdog


class WatchdogTests(unittest.TestCase):
    def test_retry_progress_does_not_trigger_restart(self):
        now=[0]
        terminated=[]
        guard=Watchdog(timeout=150,clock=lambda:now[0],terminate=lambda:terminated.append(True))
        for _ in range(10):
            now[0]+=63
            self.assertTrue(guard.check())
            guard.touch()
        self.assertEqual(terminated,[])
        now[0]+=151
        self.assertFalse(guard.check())
        self.assertEqual(terminated,[True])

    def test_frozen_process_is_terminated_for_supervisor(self):
        code='from arena.watchdog import Watchdog; import time; w=Watchdog(timeout=.1); w.start(); time.sleep(10)'
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,timeout=3)
        self.assertEqual(result.returncode,70)
        self.assertIn(b'no progress',result.stderr)


if __name__=='__main__':
    unittest.main()
