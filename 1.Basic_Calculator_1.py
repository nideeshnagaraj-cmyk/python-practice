print('\t----CALCULATOR USING TWO NUMBERS AND BASIC OPERATIONS----')
Continue=True
while Continue:
    num1=float(input("Enter the number a: "))
    num2=float(input("Enter the number b: "))
    print('''1.ADDITION(+)
2.SUBTRACTION(-)
3.MULTIPLICATION(*)
4.DIVISION(/)''')
    operator=input('Enter the operator symmbol: ')
    if '+'==operator:
        total=num1+num2
        print(f'{num1} + {num2} = {total}')
    elif '-'==operator:
        sub=num1-num2
        print(f'{num1} - {num2} = {sub}')
    elif '*'==operator:
        product=num1*num2
        print(f'{num1} * {num2} = {product:.3f}')
    elif '/'==operator:
        if num2!=0:
            division=num1/num2
            print(f'{num1} / {num2} = {division:.3f}')
        else:
            print("Division by zero(0) is invalid")
    else:
        print('Invalid Operator symbol')
    opinion=input("Do you want to do another operation (yes/no): ").lower()
    if 'no'==opinion:
        Continue=False
print("\t----Thank You----")