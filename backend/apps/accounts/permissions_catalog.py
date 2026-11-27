"""Granular permissions a Super Admin can grant to each ADMIN account.

Codes are stable identifiers (stored on the user); labels are for the UI. Adding a module
later = adding entries here and referencing the code from the new view.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionDef:
    code: str
    module: str
    label: str


ADMIN_PERMISSIONS: tuple[PermissionDef, ...] = (
    PermissionDef("platform.view", "platform", "Rollar imkoniyatlarini ko'rish"),
    PermissionDef("platform.manage", "platform", "Rollar imkoniyatlarini yoqish / o'chirish"),
    PermissionDef("dashboard.view", "dashboard", "Dashboardni ko'rish"),
    PermissionDef("users.view", "users", "Foydalanuvchilarni ko'rish"),
    PermissionDef("users.create", "users", "Foydalanuvchi qo'shish"),
    PermissionDef("users.update", "users", "Foydalanuvchini tahrirlash"),
    PermissionDef("users.delete", "users", "Foydalanuvchini o'chirish"),
    PermissionDef("users.view_pinfl", "users", "To'liq JSHSHIRni ko'rish"),
    PermissionDef("studios.view", "studios", "Studiyalarni ko'rish"),
    PermissionDef("studios.create", "studios", "Studiya qo'shish"),
    PermissionDef("studios.update", "studios", "Studiyani tahrirlash"),
    PermissionDef("studios.delete", "studios", "Studiyani o'chirish"),
    PermissionDef("venues.view", "venues", "To'yxonalarni ko'rish"),
    PermissionDef("venues.create", "venues", "To'yxona qo'shish"),
    PermissionDef("venues.update", "venues", "To'yxonani tahrirlash (zallar, rasmlar, bloklash)"),
    PermissionDef("venues.delete", "venues", "To'yxonani o'chirish"),
    PermissionDef("venues.publish", "venues", "Ommaga chiqarishni tasdiqlash / rad etish / to'xtatish"),
    PermissionDef(
        "venues.schedule", "venues", "To'yxona jadvalini boshqarish (bron tasdiqlash / rad / bekor, smenalar)"
    ),
    PermissionDef("reviews.view", "reviews", "To'yxona va studiyalar sharhlarini ko'rish"),
    PermissionDef("reviews.moderate", "reviews", "Sharhlarni yashirish / o'chirish"),
    PermissionDef("subscriptions.view", "subscriptions", "Obunalar va to'lovlarni ko'rish"),
    PermissionDef("subscriptions.create", "subscriptions", "Foydalanuvchiga obuna berish (to'lov qayd etib)"),
    PermissionDef("subscriptions.update", "subscriptions", "Obuna so'rovini tasdiqlash / rad etish / bekor qilish"),
    PermissionDef(
        "subscriptions.plans", "subscriptions", "Obuna narxlari, limitlar va to'lov ma'lumotlarini boshqarish"
    ),
    PermissionDef("backup.view", "backup", "Backup holatlari va backupdagi video-rasmlarni ko'rish"),
    PermissionDef(
        "backup.manage", "backup", "Backupga o'tkazish / chiqarish, muddatlarni uzaytirish, backupdagi faylni o'chirish"
    ),
    PermissionDef("finance.view", "finance", "Kirim-chiqim hisobotini ko'rish"),
    PermissionDef("finance.manage", "finance", "Xarajat qo'shish / o'chirish, dollar kursini o'zgartirish"),
    PermissionDef("requests.view", "requests", "So'rovlarni ko'rish (media o'chirish)"),
    PermissionDef("requests.media_delete", "requests", "Media o'chirish so'rovini tasdiqlash / rad etish"),
    PermissionDef("tryon.view", "tryon", "Virtual kiyib ko'rish katalogini ko'rish"),
    PermissionDef("tryon.create", "tryon", "Kiyim qo'shish"),
    PermissionDef("tryon.update", "tryon", "Kiyim va AR qatlamlarini tahrirlash"),
    PermissionDef("tryon.delete", "tryon", "Kiyimni o'chirish"),
    PermissionDef("tryon.approve", "tryon", "Kiyimni tasdiqlash / rad etish"),
    PermissionDef("support.view", "support", "Yordam xatlarini qabul qilish va javob berish"),
    PermissionDef(
        "support.monitor", "support", "Barcha yordam xatlarini kuzatish (adminlar xatlari ham, faqat o'qish)"
    ),
    PermissionDef("ai.view", "ai", "AI maslahatchi statistikasi, sarfi va xatolarini ko'rish"),
    PermissionDef("ai.reports", "ai", "AI javoblari bo'yicha shikoyatlarni ko'rib chiqish"),
    PermissionDef(
        "ai.conversations",
        "ai",
        "Foydalanuvchilarning AI suhbatlarini o'qish (yashirilgan, har bir ko'rish qayd etiladi)",
    ),
    PermissionDef("ai.disable", "ai", "AI maslahatchini yoki uning qismini favqulodda o'chirish"),
)

ALL_CODES: tuple[str, ...] = tuple(p.code for p in ADMIN_PERMISSIONS)
DEFAULT_ADMIN_PERMISSIONS: tuple[str, ...] = ("dashboard.view",)

MODULE_LABELS = {
    "platform": "Platforma boshqaruvi",
    "dashboard": "Dashboard",
    "users": "Foydalanuvchilar",
    "studios": "Studiyalar",
    "venues": "To'yxonalar",
    "reviews": "Sharhlar",
    "subscriptions": "Obunalar",
    "finance": "Kirim-chiqim",
    "backup": "Backup rejimi",
    "requests": "So'rovlar",
    "support": "Yordam",
    "tryon": "Virtual kiyib ko'rish",
    "ai": "AI maslahatchi",
}


def normalize(codes) -> list[str]:
    """Deduplicate and order codes as in the catalog. Unknown codes must be rejected before this."""
    wanted = set(codes or ())
    return [code for code in ALL_CODES if code in wanted]
