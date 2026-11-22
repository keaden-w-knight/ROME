#version 450

// Per-vertex: position and normal from the bound vertex buffer.
layout(location = 0) in vec3 in_position;
layout(location = 1) in vec3 in_normal;

// Per-draw: the full MVP for clip position, and the model matrix so the normal
// can be taken to world space. Uniform scale only, so mat3(model) suffices.
layout(push_constant) uniform Push {
    mat4 mvp;
    mat4 model;
} pc;

layout(location = 0) out vec3 v_normal;

void main() {
    gl_Position = pc.mvp * vec4(in_position, 1.0);
    v_normal = mat3(pc.model) * in_normal;
}
