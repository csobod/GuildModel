# Boot via the light launcher so the splash shows before the heavy VTK import
# (guildmodel/gui/boot.py). Importing guildmodel.gui.app here would pay that
# import cost before any feedback reaches the screen.
from guildmodel.gui.boot import main

if __name__ == "__main__":
    main()
