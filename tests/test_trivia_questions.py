import unittest

from jellydisc.jellyfin_client import Episode
from jellydisc.menu_builder import generate_trivia_questions


class TriviaQuestionTests(unittest.TestCase):
    def test_generates_twenty_show_specific_questions_deterministically(self):
        episodes = [
            Episode(
                id=str(index),
                name=f"Story {index}",
                index_number=index,
                overview=f"The characters investigate mystery number {index}.",
            )
            for index in range(1, 9)
        ]
        arguments = {
            "series_name": "Example Show",
            "season_name": "Season 2",
            "release_year": "2024",
            "episodes": episodes,
            "actors": [
                "Alex Actor as Avery",
                "Blair Performer as Bailey",
                "Casey Star as Cameron",
                "Devon Player as Drew",
            ],
            "directors": ["Dana Director"],
            "writers": ["Wren Writer"],
        }

        first = generate_trivia_questions(**arguments)
        second = generate_trivia_questions(**arguments)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 20)
        for question in first:
            self.assertEqual(len(question["options"]), 4)
            self.assertIn(
                question["correct_index"], range(len(question["options"]))
            )
            self.assertNotIn("DVD", question["question"])
            self.assertNotIn("aspect ratio", question["question"].lower())

    def test_sparse_metadata_uses_general_film_and_tv_bonus_questions(self):
        questions = generate_trivia_questions(
            "Example Show",
            "Season 1",
            None,
            [Episode(id="1", name="Pilot", index_number=1)],
        )

        self.assertEqual(len(questions), 20)
        for question in questions:
            self.assertNotIn("DVD", question["question"])
            self.assertNotIn("aspect ratio", question["question"].lower())


if __name__ == "__main__":
    unittest.main()
