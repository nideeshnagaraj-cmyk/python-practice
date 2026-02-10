s='dvdf'
z=[]
n=''
for i in s:
    if i not in n:
        n=n+i
    else:
        z.append(len(n))
        n = n[n.index(i) + 1:] + i
z.append(len(n))
print(max(z))