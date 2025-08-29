#!/usr/bin/env python3
"""
gamecontroller.py
Utility for handling game controllers (joysticks, throttles, pedals).
Uses pygame for cross-platform input.
"""

import pygame

class GameController:
    def __init__(self, guid: str = None, index: int = None):
        """
        Create a controller instance by GUID or index.
        GUID preferred (stable across reboots).
        """
        pygame.init()
        pygame.joystick.init()

        if guid is not None:
            # Try to find joystick with matching GUID
            for i in range(pygame.joystick.get_count()):
                js = pygame.joystick.Joystick(i)
                if js.get_guid() == guid:
                    self.joystick = js
                    self.joystick.init()
                    break
            else:
                raise ValueError(f"No joystick with GUID {guid}")
        elif index is not None:
            if index >= pygame.joystick.get_count():
                raise ValueError(f"No joystick at index {index}")
            self.joystick = pygame.joystick.Joystick(index)
            self.joystick.init()
        else:
            raise ValueError("Must provide either GUID or index")

    @staticmethod
    def list_devices():
        """
        Return list of all connected devices with (index, guid, name).
        """
        pygame.init()
        pygame.joystick.init()
        devices = []
        for i in range(pygame.joystick.get_count()):
            js = pygame.joystick.Joystick(i)
            devices.append((i, js.get_guid(), js.get_name()))
        return devices

    def get_guid(self) -> str:
        return self.joystick.get_guid()

    def get_name(self) -> str:
        return self.joystick.get_name()

    def get_axis(self, axis: int) -> float:
        """
        Return axis value in range [-1.0, 1.0].
        """
        pygame.event.pump()
        return self.joystick.get_axis(axis)

    def get_button(self, button: int) -> bool:
        """
        Return True if button is pressed.
        """
        pygame.event.pump()
        return bool(self.joystick.get_button(button))

    def get_hat(self, hat: int = 0) -> tuple[float, float]:
        """
        Return hat state as (x, y).
        """
        pygame.event.pump()
        return self.joystick.get_hat(hat)
