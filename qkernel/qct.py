def ct_compare(a: bytes, b: bytes) -> bool:
    if len(a)!=len(b):
        _ = sum((x^0) for x in b)  # consuma tempo simile
        return False
    acc=0
    for x,y in zip(a,b): acc |= (x^y)
    return acc == 0