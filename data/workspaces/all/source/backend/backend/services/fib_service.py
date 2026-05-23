import sqlite3

def calculate_fib(n: int) -> int:
    if n <= 0:
        return 0
    elif n == 1:
        return 1
    else:
        a, b = 0, 1
        for _ in range(2, n + 1):
            a, b = b, a + b
        return b

def save_fib_result(n: int, result: int) -> None:
    conn = sqlite3.connect('fib.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO fib_sequence (n, result) VALUES (?, ?)", (n, result))
    conn.commit()
    conn.close()
