#!/usr/bin/perl

use strict;
use warnings;
no warnings 'uninitialized';

use feature "switch";

use DBI;
#use Fcntl qw/:flock SEEK_END/;
use Storable qw/freeze thaw/;

require "./conf.pl";

our($db,$db_user,$db_pwd);

my %session;
my %auth_params;

my $logd_in = 0;
my $authd = 0;

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;

	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}
	#logged in 
	if (exists $session{"id"}) {
		$logd_in++;
		my $id = $session{"id"};
		if ($id eq "1") {
			$authd++;
		}
	}
}

my $content = '';
my $js = '';
my $feedback = '';

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/administrator.html">Administrator Panel</a> --&gt; <a href="/yans/">Yans Timetable Builder</a> --&gt; <a href="/cgi-bin/edittimetable.cgi">Manually Edit Timetable</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Yans: Timetable Builder - Manually Edit Timetable</title>
</head>
<body>
$header
<p><span style="color: red">Sorry, you do not have the appropriate privileges to edit the timetable.</span> Only the administrator is authorized to take this action.
</body>
</html> 
*;
		print "Status: 200 OK\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";

		my $len = length($content);
		print "Content-Length: $len\r\n";

		my @new_sess_array = ();

		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};        
		}
		my $new_sess = join ('&',@new_sess_array);

		print "X-Update-Session: $new_sess\r\n";

		print "\r\n";
		print $content;
		exit 0;
	}
	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/edittimetable.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Yans: Timetable Builder - Manually Edit Timetable</title>
</head>
<body>
You should have been redirected to <a href="/login.html?cont=/cgi-bin/edittimetable.cgi">/login.html?cont=/cgi-bin/edittimetable.cgi</a>. If you were not, <a href="/login.html?cont=/cgi-bin/edittimetable.cgi">click here</a> 
</body>
</html>!;

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}
my $post_mode = 0;

if ( exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST" ) {
	
	my $str = "";

	while (<STDIN>) {
               	$str .= $_;
       	}

	my $space = " ";
	$str =~ s/\x2B/$space/ge;
	my @auth_req = split/&/,$str;
	
	for my $auth_req_line (@auth_req) {
		my $eqs = index($auth_req_line, "=");	
		if ($eqs > 0) {
			my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1)); 
			$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;

			#ran into problems handling SELECT with 'multiple' set.
			if (exists $auth_params{$k}) {
				unless ( ref($auth_params{$k}) eq "ARRAY") {
					$auth_params{$k} = [$auth_params{$k}];
				}
				push @{$auth_params{$k}}, $v;
			}
			else {
				$auth_params{$k} = $v;
			}
		}
	}
	#processing data sent 
	$post_mode++;
}



my $con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});
#read currently active timetable
#
my ($id,@selected_classes,%selected_days,%exception_days,%day_orgs,%machine_day_orgs,%lesson_assignments,%day_org_num_events,%lesson_to_teachers,%teachers) = (undef,undef,undef,undef,undef,undef,undef,undef,undef,undef);

my $prep_stmt_2 = $con->prepare("SELECT id, selected_classes, selected_days, exception_days, day_orgs, machine_day_orgs, lesson_assignments, day_org_num_events, lesson_to_teachers, teachers FROM timetables WHERE is_committed=1 ORDER BY id DESC LIMIT 1");

if ($prep_stmt_2) {
	my $rc = $prep_stmt_2->execute();
	if ($rc) {
		while (my @rslts = $prep_stmt_2->fetchrow_array()) {

			$id = $rslts[0];

			@selected_classes = @{ (thaw($rslts[1])) };
			%selected_days = %{thaw($rslts[2])};
			%exception_days = %{thaw($rslts[3])};
			%day_orgs = %{thaw($rslts[4])};
			%machine_day_orgs = %{thaw($rslts[5])};
			%lesson_assignments = %{thaw($rslts[6])};
			%day_org_num_events = %{thaw($rslts[7])};
			%lesson_to_teachers = %{thaw($rslts[8])};
			%teachers = %{thaw($rslts[9])};
		}
	}
	else {
		print STDERR "Could not execute SELECT FROM timetables", $prep_stmt_2->errstr, $/;
	}
}
else {
	print STDERR "Could not prepare SELECT FROM timetables", $prep_stmt_2->errstr, $/;
}

if ( $post_mode ) {

PM: {

	unless ( exists $session{"confirm_code"} and exists $auth_params{"confirm_code"} and $session{"confirm_code"} eq $auth_params{"confirm_code"} ) {
		$feedback = qq!<p><span style="color: red">Invalid tokens passed</span>. Do not alter the hidden values in the HTML form!;
		$post_mode = 0;
		last PM;
	}
	
	unless (exists $auth_params{"class"}) {
		$feedback = qq!<p><span style="color: red">No class specified</span>!;
		$post_mode = 0;
		last PM;
	}

	my $class = $auth_params{"class"};
	#verify class
	my $valid_class = 0;
	foreach (@selected_classes) {
		#should match case
		if ( $class eq $_ ) {
			$valid_class = 1;
			last;
		}
	}
	unless ($valid_class) {
		$feedback = qq!<p><span style="color: red">Invalid class specified<span>!;
		$post_mode = 0;
		last PM;
	}

	unless (exists $auth_params{"day_1"}) {
		$feedback = qq!<p><span style="color: red">You did not specify a day.</span>!;
		$post_mode = 0;
		last PM;
	}

	my $day_1 = $auth_params{"day_1"};
	
	unless (exists $selected_days{$day_1}) {
		$feedback = qq!<p><span style="color: red">Invalid day selected.</span>!;
		$post_mode = 0;
		last PM;
	}

	unless (exists $auth_params{"day_2"}) {
		$feedback = qq!<p><span style="color: red">You did not specify a day.</span>!;
		$post_mode = 0;
		last PM;
	}

	my $day_2 = $auth_params{"day_2"};
	
	unless (exists $selected_days{$day_2}) {
		$feedback = qq!<p><span style="color: red">Invalid day selected.</span>!;
		$post_mode = 0;
		last PM;
	}

	unless (exists $auth_params{"day_1_event"}) {
		$feedback = qq!<p><span style="color: red">You did not specify a lesson to swap.</span>!;
		$post_mode = 0;
		last PM;
	}

	my $day_1_event = $auth_params{"day_1_event"};

	unless ( exists $lesson_assignments{$class}->{$day_1}->{$day_1_event} ) {
		$feedback = qq!<p><span style="color: red">One of the lessons specified for the swap is invalid.</span>!;
		$post_mode = 0;
		last PM;
	}

	unless (exists $auth_params{"day_2_event"}) {
		$feedback = qq!<p><span style="color: red">You did not specify a lesson to swap.</span>!;
		$post_mode = 0;
		last PM;
	}

	my $day_2_event = $auth_params{"day_2_event"};

	unless ( exists $lesson_assignments{$class}->{$day_2}->{$day_2_event} ) {
		$feedback = qq!<p><span style="color: red">One of the lessons specified for the swap is invalid.</span>!;
		$post_mode = 0;
		last PM;
	}

	my @event_1_lessons = keys %{$lesson_assignments{$class}->{$day_1}->{$day_1_event}};
	my @event_2_lessons = keys %{$lesson_assignments{$class}->{$day_2}->{$day_2_event}};

	$lesson_assignments{$class}->{$day_1}->{$day_1_event} = {};
	$lesson_assignments{$class}->{$day_2}->{$day_2_event} = {};

	foreach (@event_1_lessons) {
		${$lesson_assignments{$class}->{$day_2}->{$day_2_event}}{$_}++;
	}

	foreach (@event_2_lessons) {
		${$lesson_assignments{$class}->{$day_1}->{$day_1_event}}{$_}++;
	}


	my $prep_stmt_3 = $con->prepare("UPDATE timetables SET lesson_assignments=? WHERE id=? LIMIT 1");

	if ($prep_stmt_3) {

		my $frozen_lesson_assignments = freeze(\%lesson_assignments);

		my $rc = $prep_stmt_3->execute($frozen_lesson_assignments, $id);

		if ( $rc ) {

			$con->commit();
			$feedback = qq*<p><span style="color: green">Lesson swap successfully performed!</span> Would you like to perform another swap?*;
			$post_mode = 0;
			last PM;

		}
	
	}
	else {
		print STDERR "Could not prepare SELECT FROM timetables", $prep_stmt_3->errstr, $/;
	}	
	#print "X-Debug: swap $class $day_1 | $day_1_event ($event_1_lessons) with $day_2 | $day_2_event ($event_2_lessons)\r\n";

}
}
if ( not $post_mode ) {


	my $classes_select = qq!<SELECT name="class" id="class" onclick="check_lessons()">!;

	my @selected_classes_js_bts = ();
	foreach ( sort {$a cmp $b} @selected_classes ) {
		push @selected_classes_js_bts, qq!'$_'!;
		$classes_select .= qq!<OPTION value="$_" title="$_">$_</OPTION>!;
	}
	my $selected_classes_js_str = join(", ", @selected_classes_js_bts);

	$classes_select .= qq!</SELECT>!;

	my $day_select_1 = qq!<SELECT name="day_1" id="day_1_select" onchange="check_lessons()">!;
	my $day_select_2 = qq!<SELECT name="day_2" id="day_2_select" onchange="check_lessons()">!;

	my @selected_days_js_bts = ();
	foreach ( keys %selected_days ) {
		push @selected_days_js_bts, qq!'$_'!;
		$day_select_1 .= qq!<OPTION value="$_" title="$_">$_</OPTION>!;
		$day_select_2 .= qq!<OPTION value="$_" title="$_">$_</OPTION>!;
	}

	my $selected_days_js_str = join(", ", @selected_days_js_bts); 

	$day_select_1 .= qq!</SELECT>!;
	$day_select_2 .= qq!</SELECT>!;

	my @teachers_js_bts = ();
	for my $ta_id (sort {$a <=> $b} keys %teachers) {
		push @teachers_js_bts, qq!{id: $ta_id, name: '$teachers{$ta_id}->{"name"}'}!;
	}
	my $teachers_js_str = join(", ", @teachers_js_bts);

	my $max_event = 0;

	my %teacher_assignments = ();
	my %lesson_assignments_remap = ();

	for my $class ( keys %lesson_assignments ) {
		for my $day ( keys %{$lesson_assignments{$class}} ) {

			my $organization = 0;
			if ( exists $exception_days{$day} ) {
				$organization = $exception_days{$day};
			}

			for my $event ( keys %{${$lesson_assignments{$class}}{$day}} ) {

				next unless ($machine_day_orgs{$organization}->{$event}->{"type"} == 0);

				for my $lesson ( keys %{${${$lesson_assignments{$class}}{$day}}{$event}} ) {
	
					if ( exists $lesson_to_teachers{lc("$lesson($class)")} ) {

						my @tas = @{$lesson_to_teachers{lc("$lesson($class)")}};
						foreach (@tas) {

							${$teacher_assignments{$_}}{"$class-$day-$event"}++;
							${$lesson_assignments_remap{"$class-$day-$event"}}{$lesson}++;

						}
					}
				}

				if ($event > $max_event) {
					$max_event = $event;
				}
			}
		}
	}
	$max_event++;

	my @ta_assignments_js_bts = ();

	for my $ta ( keys %teacher_assignments ) {

		my @assignments = keys %{$teacher_assignments{$ta}};
		my @assignments_js_bts = ();

		for my $assignment ( @assignments ) {
			push @assignments_js_bts, qq!'$assignment'!;
		}

		my $assignments_js_str = join(", ", @assignments_js_bts);
		push @ta_assignments_js_bts, qq!{id: $ta, assignments: [$assignments_js_str]}!;

	}

	
	my $ta_assignments_js_str = join(", ", @ta_assignments_js_bts);

	my @lesson_assignments_js_bts = ();

	for my $spot ( keys %lesson_assignments_remap ) {

		my @lessons = ();
		foreach ( keys %{$lesson_assignments_remap{$spot}} ) {
			push @lessons, qq!'$_'!;
		}
		my $lessons_str = join(", ", @lessons);

		push @lesson_assignments_js_bts, qq!{spot: '$spot', lessons: [$lessons_str]}!;
	}
 
	my $lesson_assignments_js_str = join(", ", @lesson_assignments_js_bts);	

	my @lesson_to_tas_js_bts = ();

	for my $lesson (keys %lesson_to_teachers) {

		my $tas_js = '[' . join(", ", @{$lesson_to_teachers{$lesson}}) . ']';
		push @lesson_to_tas_js_bts, qq!{lesson: '$lesson', tas: $tas_js}!;
		
	}

	my $lesson_to_tas_js_str = join(", ", @lesson_to_tas_js_bts);

	my $js = 
qq*

	var classes = [$selected_classes_js_str];
	var days = [$selected_days_js_str];
	var teachers = [$teachers_js_str];

	var teacher_assignments = [$ta_assignments_js_str];
	var lesson_assignments = [$lesson_assignments_js_str];
	var lesson_to_tas = [$lesson_to_tas_js_str];

	var max_event = $max_event;

	var spot_re = /\\-(\\d+)\$/;

	function check_lessons() {

		var class_name = document.getElementById("class").value;
		
		var day_1 = document.getElementById("day_1_select").value;
		var day_2 = document.getElementById("day_2_select").value;

		var all_day_1_spots = [];
		var all_day_2_spots = [];

		for (var i = 0; i < max_event; i++) {
			all_day_1_spots.push(class_name + "-" + day_1 + "-" + i);
			all_day_2_spots.push(class_name + "-" + day_2 + "-" + i);
		}

		var current_event_1 = "0";
		if (document.getElementById("day_1_event") ) {
			current_event_1 = document.getElementById("day_1_event").value;
		}

		var current_event_2 = "0";
		if (document.getElementById("day_2_event") ) {
			current_event_2 = document.getElementById("day_2_event").value;
		}

	
		var event_selection_1 = new RegExp("\\-" + day_1 + "\\-" + current_event_1 + "\$");
		var event_selection_2 = new RegExp("\\-" + day_2 + "\\-" + current_event_2 + "\$");	

		var day_1_lesson_select = "<SELECT name='day_1_event' id='day_1_event' onchange='check_lessons()'>";
		var day_2_lesson_select = "<SELECT name='day_2_event' id='day_2_event' onchange='check_lessons()'>";

		var teachers_1 = [];
		var teachers_2 = [];

		var current_spot_1 = "";
		var day_2_lesson_adds = 0;
 
		for ( var i = 0; i < all_day_1_spots.length; i++ ) {

			for ( var j = 0; j < lesson_assignments.length; j++ ) {
				if (lesson_assignments[j].spot == all_day_1_spots[i]) {

					var spot_matched = all_day_1_spots[i].match(spot_re);
					if ( spot_matched ) {

						var event = spot_matched[1];
						var lessons_str = lesson_assignments[j].lessons.join(", ");
	
						var selected = "";
						if (event == current_event_1) {
		
							current_spot_1 = all_day_1_spots[i];

							selected = "selected ";
							for ( var m = 0; m < (lesson_assignments[j].lessons).length; m++ ) {
								var lesson_name = ((lesson_assignments[j].lessons)[m] + "(" + class_name + ")").toLowerCase();
								for ( var l = 0; l < lesson_to_tas.length; l++ ) {
									if ( lesson_name == lesson_to_tas[l].lesson ) {
										for ( var k = 0; k < (lesson_to_tas[l].tas).length; k++ ) {
											teachers_1.push((lesson_to_tas[l].tas)[k]);
										}
										break;
									}
								}
							}
						}

						day_1_lesson_select += "<OPTION " + selected + "value='" + event + "'" + " title='" + event + " " + lessons_str + "'>" + event + " " + lessons_str + "</OPTION>";
					}
					break;	
				}
			}

		}
	
		day_1_lesson_select += "</SELECT>";

		for ( var i = 0; i < all_day_2_spots.length; i++ ) {

			for ( var j = 0; j < lesson_assignments.length; j++ ) {

				if ( lesson_assignments[j].spot == all_day_2_spots[i] ) {

					var match_possible = true;

					var spot_matched = all_day_2_spots[i].match(spot_re);

					if ( spot_matched ) {

						var event = spot_matched[1];
						var lessons_str = lesson_assignments[j].lessons.join(", ");

						var event_selection_str = all_day_2_spots[i].substr(class_name.length);
						var event_selection_re = new RegExp(event_selection_str + "\$");

						//check if teacher(s) 1 can be put into selection 2
						for (var n = 0; n < teachers_1.length; n++) {
								
							for ( var o = 0; o < teacher_assignments.length; o++ ) {
								if ( teacher_assignments[o].id == teachers_1[n] ) {	

									//check if any of the assignments correspond with selection 1
									for (var p = 0; p < (teacher_assignments[o].assignments).length; p++) {	

										//would create collision
										if ( (teacher_assignments[o].assignments)[p].match(event_selection_re) ) {	
											match_possible = false;	
											break;
										}

									}
									break;
								}
							}
							if (!match_possible) {
								break;
							}
						}

						if (!match_possible) {	
							continue;
						}

						var teachers_2_temp = [];

						for ( var m = 0; m < (lesson_assignments[j].lessons).length; m++ ) {

							var lesson_name = ((lesson_assignments[j].lessons)[m] + "(" + class_name + ")").toLowerCase();
							for ( var l = 0; l < lesson_to_tas.length; l++ ) {
								if ( lesson_name == lesson_to_tas[l].lesson ) {
									for ( var k = 0; k < (lesson_to_tas[l].tas).length; k++ ) {
										teachers_2_temp.push((lesson_to_tas[l].tas)[k]);
									}
									break;
								}
							}

						}


						for (var n = 0; n < teachers_2_temp.length; n++) {
	
							for ( var o = 0; o < teacher_assignments.length; o++ ) {

								if ( teacher_assignments[o].id == teachers_2_temp[n] ) {
	
									//check if any of the assignments correspond with selection 1
									for (var p = 0; p < (teacher_assignments[o].assignments).length; p++) {
	
										//would create collision
										if ( (teacher_assignments[o].assignments)[p].match(event_selection_1) ) {
											//document.getElementById("debug").innerHTML +="<br> cannot put " + teachers_2[n] + " " + current_event_2 + " @ " + event_selection_1.toString();  
											match_possible = false;
											break;
										}
									}
									break;
								}

							}
							if (!match_possible) {
								break;
							}
						}

						if (!match_possible) {	
							continue;
						}


						var selected = "";

						if (event == current_event_2) {

							selected = "selected ";
							teachers_2 = teachers_2_temp;
						}

						if (match_possible) {
							day_2_lesson_select += "<OPTION " + selected + "value='" + event + "'" + " title='" + event + " " + lessons_str + "'>" + event + " " + lessons_str + "</OPTION>";
							day_2_lesson_adds++;
						}
					}
					break;
				}
			}
		}

		day_2_lesson_select += "</SELECT>";

		//No lessons were available
		if (day_2_lesson_adds == 0) {
			day_2_lesson_select = "&nbsp;<span style='color: red'>No lesson available for swapping on this day</span>";
			document.getElementById("swap_button").disabled = true;
		}
		else {
			document.getElementById("swap_button").disabled = false;
		}

		document.getElementById("lessons_1").innerHTML = day_1_lesson_select;
		document.getElementById("lessons_2").innerHTML = day_2_lesson_select;

		var teachers_1_names = [];
		for ( var i = 0; i < teachers_1.length; i++ ) {

			for ( var j = 0; j < teachers.length; j++ ) {
				if ( teachers_1[i] == teachers[j].id ) {
					teachers_1_names.push(teachers[j].name);
					break;
				}
			}

		}

		document.getElementById("teachers_1").innerHTML = teachers_1_names.join(", ");

		var teachers_2_names = [];

		for ( var i = 0; i < teachers_2.length; i++ ) {

			for ( var j = 0; j < teachers.length; j++ ) {
				if ( teachers_2[i] == teachers[j].id ) {
					teachers_2_names.push(teachers[j].name);
					break;
				}
			}

		}

		document.getElementById("teachers_2").innerHTML = teachers_2_names.join(", ");
	}

	
*;

	my $conf_code = gen_token();
	$session{"confirm_code"} = $conf_code;

	$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<script type="text/javascript">
$js
</script>
<title>Yans: Timetable Builder - Manually Edit Timetable</title>
</head>
<BODY onload="check_lessons()">

$header
$feedback
<FORM method="POST" action="/cgi-bin/edittimetable.cgi">

<INPUT type="hidden" name="confirm_code" value="$conf_code">
 
<TABLE cellpadding="10%" cellspacing="10%">

<TR><TD colspan="2"><LABEL for="class">Class</LABEL>&nbsp;$classes_select
<TR style="font-weight: bold"><TD style="border-right: solid">Swap...<TD>With...
<TR><TD style="border-right: solid"><LABEL for="day_1_select">Day</LABEL>&nbsp;$day_select_1<TD><LABEL for="day_2_select">Day</LABEL>&nbsp;$day_select_2
<TR>
<TD style="border-right: solid"><LABEL for="lessons_1">Lesson</LABEL><span id="lessons_1"></span>
<TD><LABEL for="lessons_1">Lesson</LABEL><span id="lessons_2"></span>
<TR>
<TD style="border-right: solid">Teacher(s):<span id="teachers_1" style="font-weight: bold"></span>
<TD>Teacher(s):<span id="teachers_2" style="font-weight: bold"></span>
<TR><TD colspan="2"><INPUT type="submit" name="swap" value="Swap" id="swap_button">

</TABLE>

</FORM>
<P><DIV id="debug"></DIV>
</BODY>
</HTML>
*;

}

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

my @new_sess_array = ();

for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}
my $new_sess = join ('&',@new_sess_array);

print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;
$con->disconnect() if (defined $con and $con);


sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}
