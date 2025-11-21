import unittest
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from security import validate_password_strength

class TestPasswordStrength(unittest.TestCase):
    def test_short_password(self):
        self.assertFalse(validate_password_strength("Short1!"))

    def test_no_uppercase(self):
        self.assertFalse(validate_password_strength("weakpassword1!"))

    def test_no_lowercase(self):
        self.assertFalse(validate_password_strength("WEAKPASSWORD1!"))

    def test_no_digit(self):
        self.assertFalse(validate_password_strength("WeakPassword!"))

    def test_no_special(self):
        self.assertFalse(validate_password_strength("WeakPassword1"))

    def test_strong_password(self):
        self.assertTrue(validate_password_strength("StrongP@ssw0rd123!"))

if __name__ == '__main__':
    unittest.main()
