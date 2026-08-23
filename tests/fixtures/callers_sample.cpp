void helper() {}

void caller1() {
    helper();
    helper();
}

int main() {
    caller1();
    helper();
}
