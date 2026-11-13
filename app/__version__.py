# The one place the app's version is set (MAJOR.MINOR.PATCH, semantic versioning).
# Read by the UI/logs, the PyInstaller build, the Inno Setup installer and the
# update checker. A release is published by tagging the commit "v" + this value;
# the release workflow refuses to build if the tag and this value disagree.
__version__ = "1.0.5"

# before release
# pytest                                   # 1. tests pass?
# # 2. edit app/__version__.py  ->  __version__ = "1.0.x"
# git add -A                               # 3. stage the changes
# git commit -m "release 1.0.x: update tab in settings"
# git push origin master                   # 4. send the commit (builds, but releases nothing)
# git tag v1.0.x                           # 5. label that commit with the version
# git push origin v1.0.x                   # 6. send the tag -> this makes the release