extends Node

# method to test statements
func method():
	
	pass
	
	var i = 0
	
	if ABC:
		assert(false)
	elif false:
		print("Hello"+" "+"World")
	elif true:
		print("Goodbye ", "World")
	else:
		print(i)
	
	while false:
		i += 1
		break
		continue
	
	for j in range(i):
		i += j
	
	match i:
		"1":
			print(i)
		1:
			print(i)
		0 when true:
			print("zero!")
		var x when false:
			print("unreachable")
		[var x, var y] when true:
			print("array pattern")
		{var x : var y} when true:
			print("dictionary pattern")
		_:
			print("unknown")
	
	i += 3/3 + 2*.5
	
	return []
	