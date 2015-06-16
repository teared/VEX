"${afile:s/f/dsf/} sd"

# Data types allowed on objects.
dopdatahint -t SIM_Data SIM_Object

foreach i ( a b c )
    echo $i
end

foreach object ( "`run("opls -d")`" )
    echo Object $object
end

set foo = "Hello world"
echo '$foo='"$foo"
$foo=Hello world

echo ${afile:e}


# Script for a guessing game (guess.cmd)

# First, get a random seed

set foo = `system(date)`
set seed = `substr($foo, 14, 2)``substr($foo, 17, 2)`

# Then, pick a random number

set num = `int(rand($seed)*100)+1`

set guess = -1
echo Guess a random number between 1 and 100.

while ( "$guess" != "$num" )
    echo "-n Enter guess (q to quit): "
    read guess

    if ( "$guess" == q || "$guess" == "") then
        break;
    endif

    # Convert to a number
    set iguess = `atof($guess)`

    if ( $iguess < $num ) then
        echo Too low
    else if ( $iguess > $num ) then
        echo Too high
    else
        echo Spot on!
    endif
end

echo The number was $num