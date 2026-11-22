#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/tuple.h>
#include <nanobind/stl/vector.h>

#include <cstdint>
#include <tuple>
#include <vector>

#include "rome/app.hpp"
#include "rome/error.hpp"
#include "rome/types.hpp"
#include "rome/window.hpp"

namespace nb = nanobind;
using namespace nb::literals;

namespace {

/// Colours are accepted as (r, g, b) or (r, g, b, a) tuples, which is what a
/// pygame user will reach for first.
rome::Color color_from_tuple(const nb::tuple& value) {
    const std::size_t size = nb::len(value);
    if (size != 3 && size != 4) {
        throw nb::value_error("colour must be a 3- or 4-tuple of floats in 0..1");
    }
    rome::Color color{};
    color.r = nb::cast<float>(value[0]);
    color.g = nb::cast<float>(value[1]);
    color.b = nb::cast<float>(value[2]);
    color.a = size == 4 ? nb::cast<float>(value[3]) : 1.0F;
    return color;
}

nb::tuple color_to_tuple(rome::Color color) {
    return nb::make_tuple(color.r, color.g, color.b, color.a);
}

}  // namespace

NB_MODULE(_rome, m) {
    m.doc() = "Vulkan-backed 3D viewport primitives (native extension)";

    m.attr("__version__") = ROME_VERSION;

    // rome::Error surfaces in Python as rome.RomeError, so callers can catch
    // every failure from the renderer with one except clause.
    nb::exception<rome::Error>(m, "RomeError");

    nb::class_<rome::App>(m, "App", "A window with a Vulkan surface and a render loop.")
        .def(
            "__init__",
            [](rome::App* self, int width, int height, const std::string& title, bool vsync,
               bool resizable, bool validation, nb::object clear_color) {
                rome::AppConfig config{};
                config.window.width = width;
                config.window.height = height;
                config.window.title = title;
                config.window.resizable = resizable;
                config.vsync = vsync;
                config.validation = validation;
                if (!clear_color.is_none()) {
                    config.clear_color = color_from_tuple(nb::cast<nb::tuple>(clear_color));
                }
                new (self) rome::App(config);
            },
            "width"_a = 1280, "height"_a = 720, "title"_a = "ROME", "vsync"_a = true,
            "resizable"_a = true, "validation"_a = false, "clear_color"_a = nb::none())

        .def("tick", &rome::App::tick, nb::call_guard<nb::gil_scoped_release>(),
             "Process events and draw one frame. Returns False once closed.")
        .def("run", &rome::App::run, nb::call_guard<nb::gil_scoped_release>(),
             "Run the loop until the window closes.")

        .def(
            "upload_mesh",
            [](rome::App& self, const std::vector<float>& positions,
               const std::vector<float>& normals, const std::vector<std::uint32_t>& indices) {
                return self.upload_mesh(positions, normals, indices);
            },
            "positions"_a, "normals"_a, "indices"_a,
            "Upload a mesh (flat xyz positions and normals, triangle-list indices). "
            "Returns a handle to draw it with render_scene.")

        .def(
            "render_scene",
            [](rome::App& self, nb::list instances, std::tuple<float, float, float> cam_pos,
               std::tuple<float, float, float> cam_target, std::tuple<float, float, float> up,
               float fov) {
                rome::CameraParams camera{};
                camera.position[0] = std::get<0>(cam_pos);
                camera.position[1] = std::get<1>(cam_pos);
                camera.position[2] = std::get<2>(cam_pos);
                camera.target[0] = std::get<0>(cam_target);
                camera.target[1] = std::get<1>(cam_target);
                camera.target[2] = std::get<2>(cam_target);
                camera.up[0] = std::get<0>(up);
                camera.up[1] = std::get<1>(up);
                camera.up[2] = std::get<2>(up);
                camera.fov_deg = fov;

                std::vector<rome::MeshInstance> items;
                const std::size_t count = nb::len(instances);
                items.reserve(count);
                for (std::size_t i = 0; i < count; ++i) {
                    nb::tuple t = nb::cast<nb::tuple>(instances[i]);
                    rome::MeshInstance mi{};
                    mi.mesh = nb::cast<std::uint64_t>(t[0]);
                    nb::tuple p = nb::cast<nb::tuple>(t[1]);
                    mi.position[0] = nb::cast<float>(p[0]);
                    mi.position[1] = nb::cast<float>(p[1]);
                    mi.position[2] = nb::cast<float>(p[2]);
                    nb::tuple r = nb::cast<nb::tuple>(t[2]);
                    mi.rotation[0] = nb::cast<float>(r[0]);
                    mi.rotation[1] = nb::cast<float>(r[1]);
                    mi.rotation[2] = nb::cast<float>(r[2]);
                    mi.scale = nb::cast<float>(t[3]);
                    items.push_back(mi);
                }
                return self.render_scene(items, camera);
            },
            "instances"_a, "cam_pos"_a = std::make_tuple(0.0F, 0.0F, -5.0F),
            "cam_target"_a = std::make_tuple(0.0F, 0.0F, 0.0F),
            "up"_a = std::make_tuple(0.0F, 1.0F, 0.0F), "fov"_a = 50.0F,
            "Draw one frame of a scene. instances is a list of "
            "(handle, (x,y,z), (rx,ry,rz), scale). Returns False once the window closes.")

        .def("close", &rome::App::close, "Ask the loop to stop after this frame.")

        .def_prop_ro("running", &rome::App::is_running)
        .def_prop_ro("gpu_name", &rome::App::gpu_name)
        .def_prop_ro("frame_count", &rome::App::frame_count)
        .def_prop_ro("elapsed", &rome::App::elapsed)
        .def_prop_ro("delta_time", &rome::App::delta_time)
        .def_prop_ro("fps", &rome::App::fps)

        .def_prop_ro("size",
                     [](const rome::App& self) {
                         const rome::Extent2D extent = self.size();
                         return nb::make_tuple(extent.width, extent.height);
                     })

        .def_prop_rw(
            "clear_color", [](const rome::App& self) { return color_to_tuple(self.clear_color()); },
            [](rome::App& self, const nb::tuple& value) {
                self.set_clear_color(color_from_tuple(value));
            })

        // Context-manager support, so a viewport can be scoped with `with`.
        .def(
            "__enter__", [](rome::App& self) -> rome::App& { return self; },
            nb::rv_policy::reference_internal)
        .def("__exit__", [](rome::App& self, nb::handle, nb::handle, nb::handle) { self.close(); })

        .def("__repr__", [](const rome::App& self) {
            const rome::Extent2D extent = self.size();
            return "<rome.App " + std::to_string(extent.width) + "x" +
                   std::to_string(extent.height) + " on " + self.gpu_name() + ">";
        });
}
