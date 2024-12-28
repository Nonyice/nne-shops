const slides = document.querySelectorAll('.slide');
let currentSlide = 0;
const slideInterval = 3000; // Time in milliseconds (5 seconds)

// Function to go to the next slide
function showNextSlide() {
    slides[currentSlide].classList.remove('active');
    currentSlide = (currentSlide + 1) % slides.length;
    slides[currentSlide].classList.add('active');
}

// Automatically transition slides
setInterval(showNextSlide, slideInterval);

// Allow manual navigation
document.querySelector('.prev').addEventListener('click', () => {
    slides[currentSlide].classList.remove('active');
    currentSlide = (currentSlide - 1 + slides.length) % slides.length;
    slides[currentSlide].classList.add('active');
});

document.querySelector('.next').addEventListener('click', () => {
    slides[currentSlide].classList.remove('active');
    currentSlide = (currentSlide + 1) % slides.length;
    slides[currentSlide].classList.add('active');
});
