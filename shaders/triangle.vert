#version 450

// No vertex buffer: the three corners are indexed straight out of a constant
// array by gl_VertexIndex. Keeps the first pipeline free of any buffer
// allocation or vertex-input state.
layout(location = 0) out vec3 v_color;

const vec2 kPositions[3] = vec2[](
    vec2( 0.0, -0.6),
    vec2( 0.6,  0.6),
    vec2(-0.6,  0.6)
);

const vec3 kColors[3] = vec3[](
    vec3(1.00, 0.28, 0.34),
    vec3(0.30, 0.92, 0.48),
    vec3(0.32, 0.52, 1.00)
);

void main() {
    gl_Position = vec4(kPositions[gl_VertexIndex], 0.0, 1.0);
    v_color = kColors[gl_VertexIndex];
}
