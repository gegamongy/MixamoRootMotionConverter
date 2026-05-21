A couple python scripts for extracting and removing the root motion from the "Hips" track of an animation, and copying it onto a seperate "Root" bone.

This is assuming you have an Armature with a "Root" bone on the floor, and a "Hips" bone that has the root motion animation data. 


# Mixamo Root Motion Converter
Converts the root motion from one bone (usually hips) to a new root bone (usually on the floor at (0, 0, 0)) 

1. Select the armature, then in the Action Editor select the animation you want to convert the root motion for.
2. Open the text editor and paste the python script into it.
3. Change any config values as needed to fit your project and armatures.
4. Run the script and root motion will be removed from the "Hips" bone and applied to the "Root" bone.

Video tutorial:
https://youtu.be/OQnhdJDfQJ4


# Mixamo Root Rotation Converter
Converts the root rotation from one bone to a new root bone.


# Batch Root Motion Converter
Goes through your actions, selects any containing keywords (usually anims that you will have a lot of that will need this done, so "sprint", "walk", "run" usually), and then runs the Root Motion Converter script for each one sequentially. So you don't have to manually run the root motion converter script your self on every individual animation.

Video tutorial for Root Rotation Converter and Batch Converter:

