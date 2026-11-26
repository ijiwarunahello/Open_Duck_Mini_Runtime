import pygame
from threading import Thread
from queue import Queue, Empty
import time
import numpy as np
from mini_bdx_runtime.buttons import Buttons


X_RANGE = [-0.15, 0.15]
Y_RANGE = [-0.2, 0.2]
YAW_RANGE = [-1.0, 1.0]

# rads
NECK_PITCH_RANGE = [-0.34, 1.1]
HEAD_PITCH_RANGE = [-0.78, 0.3]
HEAD_YAW_RANGE = [-0.5, 0.5]
HEAD_ROLL_RANGE = [-0.5, 0.5]

# Commands fall back to zero (stand in place) when no fresh command has been
# read for this long, e.g. when the reading thread is stuck or crashed.
WATCHDOG_TIMEOUT = 0.5  # s

# Released sticks read up to ~0.035 on the duck's controller. The policy steps
# when the command is above ~0.01, so drift alone made the duck walk.
STICK_DEADZONE = 0.1


def apply_deadzone(value, deadzone=STICK_DEADZONE):
    # Zero inside the deadzone, then rescaled so the output starts at 0 and
    # still reaches +-1 at full deflection.
    if abs(value) < deadzone:
        return 0.0
    return float(np.sign(value) * (abs(value) - deadzone) / (1 - deadzone))


def poll_events():
    # pygame 2.6.0 raises SystemError (from KeyError) when a joystick is added,
    # removed and added again before the events are read. This happens on the
    # first connection after boot, when the kernel rebinds the controller from
    # hid-generic to hid-microsoft. The events are lost; callers fall back to
    # pygame.joystick.get_count().
    try:
        return pygame.event.get()
    except SystemError as e:
        print(f"Controller events lost: {e!r} (cause {e.__cause__!r})")
        return []


def neutral_commands():
    # Same layout as get_commands(): commands, A, B, X, Y, LB, RB, LT, RT, dpad up/down
    return (np.zeros(7), False, False, False, False, False, False, 0.0, 0.0, 0)


class XBoxController:
    def __init__(self, command_freq, only_head_control=False, start_worker=True):
        self.command_freq = command_freq
        self.head_control_mode = only_head_control
        self.only_head_control = only_head_control

        self.last_commands = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self.worker_commands = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self.last_left_trigger = 0.0
        self.last_right_trigger = 0.0
        pygame.init()
        self.p1 = None
        self.p1_instance_id = None
        self.wait_for_joystick()
        self.cmd_queue = Queue(maxsize=1)
        self.last_command_time = time.time()

        self.A_pressed = False
        self.B_pressed = False
        self.X_pressed = False
        self.Y_pressed = False
        self.LB_pressed = False
        self.RB_pressed = False

        self.buttons = Buttons()

        if start_worker:
            Thread(target=self.commands_worker, daemon=True).start()

    def wait_for_joystick(self):
        announced = False
        while self.p1 is None:
            poll_events()  # lets SDL notice newly connected devices
            if pygame.joystick.get_count() > 0:
                self.open_joystick(0)
                break
            if not announced:
                print("Waiting for the controller...")
                announced = True
            time.sleep(0.5)

    def open_joystick(self, device_index):
        self.p1 = pygame.joystick.Joystick(device_index)
        self.p1.init()
        self.p1_instance_id = self.p1.get_instance_id()
        print(f"Loaded joystick with {self.p1.get_numaxes()} axes.")

    def release_buttons(self):
        self.A_pressed = False
        self.B_pressed = False
        self.X_pressed = False
        self.Y_pressed = False
        self.LB_pressed = False
        self.RB_pressed = False

    def commands_worker(self):
        while True:
            try:
                commands = self.get_commands()
            except Exception as e:
                # Keep the thread alive. No command is queued meanwhile, so the
                # watchdog in get_last_command() brings the commands to zero.
                print(f"Controller read failed: {e}")
                time.sleep(WATCHDOG_TIMEOUT)
                continue
            self.cmd_queue.put(commands)
            time.sleep(1 / self.command_freq)

    def get_commands(self):
        events = poll_events()
        for event in events:
            if (
                event.type == pygame.JOYDEVICEREMOVED
                and event.instance_id == self.p1_instance_id
            ):
                print("Controller disconnected, commands set to zero")
                self.p1 = None
                self.p1_instance_id = None
            elif event.type == pygame.JOYDEVICEADDED and self.p1 is None:
                self.open_joystick(event.device_index)

        # Device events can be lost (see poll_events), so check the count too.
        count = pygame.joystick.get_count()
        if self.p1 is not None and count == 0:
            print("Controller disconnected, commands set to zero")
            self.p1 = None
            self.p1_instance_id = None
        elif self.p1 is None and count > 0:
            self.open_joystick(0)

        if self.p1 is None:
            self.worker_commands = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            self.release_buttons()
            return neutral_commands()

        last_commands = self.worker_commands

        l_x = -1 * apply_deadzone(self.p1.get_axis(0))
        l_y = -1 * apply_deadzone(self.p1.get_axis(1))
        r_x = -1 * apply_deadzone(self.p1.get_axis(2))
        r_y = -1 * apply_deadzone(self.p1.get_axis(3))

        right_trigger = np.around((self.p1.get_axis(4) + 1) / 2, 3)
        left_trigger = np.around((self.p1.get_axis(5) + 1) / 2, 3)

        if left_trigger < 0.1:
            left_trigger = 0
        if right_trigger < 0.1:
            right_trigger = 0

        if not self.head_control_mode:
            lin_vel_y = l_x
            lin_vel_x = l_y
            ang_vel = r_x
            if lin_vel_x >= 0:
                lin_vel_x *= np.abs(X_RANGE[1])
            else:
                lin_vel_x *= np.abs(X_RANGE[0])

            if lin_vel_y >= 0:
                lin_vel_y *= np.abs(Y_RANGE[1])
            else:
                lin_vel_y *= np.abs(Y_RANGE[0])

            if ang_vel >= 0:
                ang_vel *= np.abs(YAW_RANGE[1])
            else:
                ang_vel *= np.abs(YAW_RANGE[0])

            last_commands[0] = lin_vel_x
            last_commands[1] = lin_vel_y
            last_commands[2] = ang_vel
        else:
            last_commands[0] = 0.0
            last_commands[1] = 0.0
            last_commands[2] = 0.0
            last_commands[3] = 0.0  # neck pitch 0 for now

            head_yaw = l_x
            head_pitch = l_y
            head_roll = r_x

            if head_yaw >= 0:
                head_yaw *= np.abs(HEAD_YAW_RANGE[0])
            else:
                head_yaw *= np.abs(HEAD_YAW_RANGE[1])

            if head_pitch >= 0:
                head_pitch *= np.abs(HEAD_PITCH_RANGE[0])
            else:
                head_pitch *= np.abs(HEAD_PITCH_RANGE[1])

            if head_roll >= 0:
                head_roll *= np.abs(HEAD_ROLL_RANGE[0])
            else:
                head_roll *= np.abs(HEAD_ROLL_RANGE[1])

            last_commands[4] = head_pitch
            last_commands[5] = head_yaw
            last_commands[6] = head_roll

        for event in events:
            if event.type == pygame.JOYBUTTONDOWN:

                if self.p1.get_button(0):  # A button
                    self.A_pressed = True

                if self.p1.get_button(1):  # B button
                    self.B_pressed = True

                if self.p1.get_button(3):  # X button
                    self.X_pressed = True

                if self.p1.get_button(4):  # Y button
                    self.Y_pressed = True
                    if not self.only_head_control:
                        self.head_control_mode = not self.head_control_mode

                if self.p1.get_button(6):  # LB button
                    self.LB_pressed = True

                if self.p1.get_button(7):  # RB button
                    self.RB_pressed = True

            if event.type == pygame.JOYBUTTONUP:
                self.release_buttons()

            # for i in range(10):
            #     if self.p1.get_button(i):
            #         print(f"Button {i} pressed")

        up_down = self.p1.get_hat(0)[1]

        return (
            np.around(last_commands, 3),
            self.A_pressed,
            self.B_pressed,
            self.X_pressed,
            self.Y_pressed,
            self.LB_pressed,
            self.RB_pressed,
            left_trigger,
            right_trigger,
            up_down,
        )

    def get_last_command(self):
        A_pressed = False
        B_pressed = False
        X_pressed = False
        Y_pressed = False
        LB_pressed = False
        RB_pressed = False
        up_down = 0
        try:
            (
                self.last_commands,
                A_pressed,
                B_pressed,
                X_pressed,
                Y_pressed,
                LB_pressed,
                RB_pressed,
                self.last_left_trigger,
                self.last_right_trigger,
                up_down,
            ) = self.cmd_queue.get(
                False
            )  # non blocking
            self.last_command_time = time.time()
        except Empty:
            if time.time() - self.last_command_time > WATCHDOG_TIMEOUT:
                self.last_commands = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
                self.last_left_trigger = 0.0
                self.last_right_trigger = 0.0

        self.buttons.update(
            A_pressed,
            B_pressed,
            X_pressed,
            Y_pressed,
            LB_pressed,
            RB_pressed,
            up_down == 1,
            up_down == -1,
        )

        return (
            self.last_commands,
            self.buttons,
            self.last_left_trigger,
            self.last_right_trigger,
        )

if __name__ == "__main__":
    controller = XBoxController(20)

    while True:
        print(controller.get_last_command())
        time.sleep(0.05)
