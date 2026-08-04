export function dadaSlide(effective) {
  // Photo asset lives at assets/dada.jpg. If missing, onerror removes the <img>
  // and the explicit fallback placeholder underneath shows through.
  return `<section class="dc-slide slide-dada">
  <div class="dada-left">
    <div class="dc-label">Комментарий Дады</div>
    <div class="dada-comment">${effective.dada_comment}</div>
  </div>
  <div class="dada-photo">
    <div class="dada-photo-fallback">фото<br>Дады<br>assets/dada.jpg</div>
    <img src="assets/dada.jpg" alt="Дада" onerror="this.remove()">
  </div>
</section>`;
}
