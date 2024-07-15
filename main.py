import movement

# Create a Coordinate object named 'home' with coordinates (0, 0, 0)
home = movement.Coordinate(0, 0, 0, 6000)

def main():
    while True:
        # Ask user for input
        user_input = input("Enter the X, Y, Z coordinates and speed (in mm/min) separated by spaces, 'home' to move to (0,0,0), or type 'exit' to quit: ")
        
        if user_input.lower() == 'exit':
            print("Exiting program.")
            break
        
        try:
            if user_input.lower() == 'home':
                # Move to the 'home' coordinate
                movement.move_to(home)
            else:
                # Split the input into coordinates and speed
                inputs = list(map(float, user_input.split()))
                if len(inputs) == 4:
                    x, y, z, speed = inputs
                elif len(inputs) == 3:
                    x, y, z = inputs
                    speed = 1500
                elif len(inputs) == 2:
                    x, y = inputs
                    z = 0
                    speed = 1500
                elif len(inputs) == 1:
                    x = inputs[0]
                    y = 0
                    z = 0
                    speed = 1500
                else:
                    raise ValueError

                # Create a Coordinate object
                coordinate = movement.Coordinate(x, y, z, speed)
                
                # Move to the coordinate
                movement.move_to(coordinate)
            
        except ValueError:
            print("Invalid input. Please enter numeric values for X, Y, Z coordinates and speed, separated by spaces.")

if __name__ == "__main__":
    main()