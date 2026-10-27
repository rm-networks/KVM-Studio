/** jsdom has no ResizeObserver: tests call resize() to report a new size. */
export class FakeResizeObserver {
  static instances: FakeResizeObserver[] = [];
  private readonly callback: () => void;

  constructor(callback: () => void) {
    this.callback = callback;
    FakeResizeObserver.instances.push(this);
  }

  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}

  resize(): void {
    this.callback();
  }
}
