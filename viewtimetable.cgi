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
}

my $content = '';
my $js = '';
my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/cgi-bin/viewtimetable.cgi">View Timetable</a>
	<hr> 
};

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


my $download = 0;

if ( exists $ENV{"QUERY_STRING"} ) {

	if ( $ENV{"QUERY_STRING"} =~ /\&?act=download\&?/i ) {
		$download = 1;
	}
}

my $con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

if ($post_mode) {
	if (exists $auth_params{"view"}) {

		my ($class_limd, $subject_limd, $teacher_limd) = (0,0,0);
		my (%wanted_classes,%wanted_subjects,%wanted_teachers);

		#proc classes		
		if (exists $auth_params{"classes"}) {
			if ( ref($auth_params{"classes"}) eq "ARRAY" ) {
				for my $class ( @{$auth_params{"classes"}} ) {
					#skip over '*'
					next if ($class eq "*");
					$wanted_classes{lc($class)}++;
					$class_limd++;
				}
			}
			else {
				unless ($auth_params{"classes"} eq "*") {
					$class_limd++;
					$wanted_classes{lc($auth_params{"classes"})}++;
				}
			}
		}
	
		#proc subjcts
		if (exists $auth_params{"subjects"}) {
			if ( ref($auth_params{"subjects"}) eq "ARRAY" ) {
				for my $subject ( @{$auth_params{"subjects"}} ) {
					#skip over '*'
					next if ($subject eq "*");
					$wanted_subjects{lc($subject)}++;
					$subject_limd++;
				}
			}
			else {
				unless ($auth_params{"subjects"} eq "*") {
					$subject_limd++;
					$wanted_subjects{lc($auth_params{"subjects"})}++;
				}
			}
		}

		#proc teachers
		if (exists $auth_params{"teachers"}) {
			if ( ref($auth_params{"teachers"}) eq "ARRAY" ) {
				for my $teacher ( @{$auth_params{"teachers"}} ) {
					#skip over '*'
					next if ($teacher eq "*");
					$wanted_teachers{lc($teacher)}++;
					$teacher_limd++;
				}
			}
			else {
				unless ($auth_params{"teachers"} eq "*") {
					$teacher_limd++;
					$wanted_teachers{lc($auth_params{"teachers"})}++;
				}
			}
		}

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
		$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>

<STYLE type="text/css">

\@media print {
	body {
		margin-top: 0px;
		margin-bottom: 0px;
		padding: 0px;
		font-size: 12pt;
		font-family: "Times New Roman", serif;	
	}

	div.no_header {
		display: none;
	}

	br.new_page {
		page-break-after: always;
	}

}

\@media screen {
	div.no_header {}	
	br.new_page {}

}

</STYLE>
<title>Yans: Timetable Builder - View Timetable</title>
</head>
<body>
<div class="no_header">
$header
</div>
*;
		my $num_cols = 0;
		for my $day_org_1 (keys %day_orgs) {
			if ( $day_org_num_events{$day_org_1} > $num_cols ) {
				$num_cols = $day_org_num_events{$day_org_1};
			}
		}
		my $cntr = 0;

		if ($teacher_limd) {
			my %lesson_assignments_dup = ();
			
			$lesson_assignments_dup{"?"} = {};

			for my $class (keys %lesson_assignments) {

				if ($class_limd) {
					next if ( not exists $wanted_classes{lc($class)} );
				}

				for my $day (keys %{$lesson_assignments{$class}}) {
					my $organization = 0;	
					
					if ( exists $exception_days{$day} ) {
						$organization = $exception_days{$day};
					}

					if (not exists ${$lesson_assignments_dup{"?"}}{$day}) {
						${$lesson_assignments_dup{"?"}}{$day} = {}
					}
					for my $event ( keys %{${$lesson_assignments{$class}}{$day}} ) {
						if (not exists ${${$lesson_assignments_dup{"?"}}{$day}}{$event}) {
							${${$lesson_assignments_dup{"?"}}{$day}}{$event} = {};
						}
						#take the fixed events as they are/
						if ($machine_day_orgs{$organization}->{$event}->{"type"} == 1) {
							 ${${$lesson_assignments_dup{"?"}}{$day}}{$event} = ${${$lesson_assignments{"?"}}{$day}}{$event};
						}
						else {
							my @subjects = keys %{${${$lesson_assignments{$class}}{$day}}{$event}};
							for my $subj (@subjects) {
								my @tas = @{$lesson_to_teachers{lc("$subj($class)")}};
								for (my $j = 0; $j < @tas; $j++) {
									if ( exists $wanted_teachers{$tas[$j]} ) {	
										${${${$lesson_assignments_dup{"?"}}{$day}}{$event}}{"$subj($class)"}++;
									}
								}
							}
						}
					}
				}
			}
			%lesson_assignments = %lesson_assignments_dup;
		}

		for my $class (sort {$a cmp $b} @selected_classes) {

			unless ($teacher_limd) {
				if ($class_limd) {
					next if (not exists $wanted_classes{lc($class)});
				}
			}

			else {
				$class = "?";
			}

			my $prev_org = -1;

			$content .= qq!<p><p><TABLE border="1" cellspacing="0" cellpadding="0">!;

			my $num_cols_plus_1 = $num_cols + 1;

			if ($teacher_limd) {
				my @ta_names = ();
				for my $ta (keys %wanted_teachers) {
					push @ta_names, $teachers{$ta}->{"name"};
				}

				
				my $teachers = "";
				if (scalar(@ta_names) < 5) {
					$teachers = join(", ", @ta_names);
					my $last_comma = rindex($teachers, ", ");

					if ( $last_comma >= 0 ) {
						substr($teachers, $last_comma, 2, " and ");
					}
				}

				$content .= qq!<THEAD><TR><TH colspan="$num_cols_plus_1" style="font-weight: bold; text-align: center; font-size: 1.5em">$teachers</THEAD>!;

			}
			else {
				$content .= qq!<THEAD><TR><TH colspan="$num_cols_plus_1" style="font-weight: bold; text-align: center; font-size: 1.5em">$class</THEAD>!;
			}

			foreach my $day ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday") {
				next if (not exists $selected_days{$day});

				my $organization = 0;	
				my $current_org = 0;

				if (exists $exception_days{$day}) {
					$organization = $exception_days{$day};	
					$current_org = $organization;
				}

				#draw table head
				if ($current_org != $prev_org) {
					$content .= "<THEAD><TH>&nbsp;";
					my $start_lessons = ${$day_orgs{$current_org}}{"start"};
					my ($hrs,$mins) = (0,0);
					my $colon = "";

					if ($start_lessons =~ /^(\d{1,2})(:?)(\d{1,2})$/) {
					$hrs   = $1;
						$mins  = $3;
						$colon = $2;
					}

					my $surplus_cols = $num_cols - scalar(keys %{$machine_day_orgs{$current_org}});

					for my $event (sort {$a <=> $b} keys %{$machine_day_orgs{$current_org}}) {

						my $duration = ${${$machine_day_orgs{$current_org}}{$event}}{"duration"};

						my $duration_mins = $duration % 60;
						my $duration_hrs = int($duration / 60);
							
						my $stop_hrs = $hrs + $duration_hrs; 
						my $stop_mins = $mins + $duration_mins;

						if ($stop_mins >= 60) {
							$stop_mins = $stop_mins - 60;
							$stop_hrs++;
						}

						my ($display_hrs,$display_stop_hrs) = ($hrs,$stop_hrs);

						#convert to 12hr clock system
						my $am_pm = "AM";
						if ($display_hrs >= 12) {
							if ($display_hrs > 12) {
								$display_hrs -= 12;
							}

							$am_pm = "PM"; 
						}
						else {
							if ($display_hrs == 0) {
								$display_hrs = 12;
							}	
						}

						if ($display_stop_hrs >= 12) {
							if ($display_stop_hrs > 12) {
								$display_stop_hrs -= 12;
							}
							$am_pm = "PM"; 
						}
						else {
							if ($display_stop_hrs == 0) {
								$display_stop_hrs = 12;
							}	
						}

						($display_hrs,$mins,$display_stop_hrs,$stop_mins) = (sprintf("%02d", $display_hrs), sprintf("%02d", $mins), sprintf("%02d", $display_stop_hrs), sprintf("%02d", $stop_mins));	

						my $time = "${display_hrs}${colon}${mins}${am_pm} - ${display_stop_hrs}${colon}${stop_mins}${am_pm}";
						my $colspan = "";

						$colspan = qq! colspan="2"! if ($surplus_cols-- > 0);
						$content .= qq!<TH${colspan} style="font-weight: bold">$time!;

						$hrs  = $stop_hrs;
						$mins = $stop_mins;
					}
					$content .= "</THEAD>";
				}

				#draw table body
				$content .= qq!<TBODY><TR><TD style="font-weight: bold">$day!;
			
				my $surplus_cols = $num_cols - scalar(keys %{$machine_day_orgs{$current_org}});

				for my $event (sort {$a <=> $b} keys %{$machine_day_orgs{$current_org}}) {	

					my @subjs = ();
	
					if (scalar ( keys %{${${$lesson_assignments{$class}}{$day}}{$event}} ) > 0) {

						my @subjects = sort{ $a cmp $b } keys %{${${$lesson_assignments{$class}}{$day}}{$event}};
						
						if ($subject_limd) {

							for ( my $i = 0; $i < @subjects; $i++ ) {
								my $resolved = 0;
								for my $subj (keys %wanted_subjects) {
									#did not use exists because
									#teacher limd lesson_assignments lessons
									#will be of the form subject(class)
									if ( lc($subjects[$i]) =~ /^$subj/ ) {
										push @subjs, $subjects[$i];	
										last;
									}
								}
							}
						}
						else {
							@subjs = sort {$a cmp $b} keys %{${${$lesson_assignments{$class}}{$day}}{$event}};
						}
					}
					
					my $name = "";

					if (scalar ( keys %{${${$lesson_assignments{$class}}{$day}}{$event}} ) > 0) {

						if ($machine_day_orgs{$current_org}->{$event}->{"type"} == 1) {
							$name = join("<BR>", keys %{${${$lesson_assignments{$class}}{$day}}{$event}});	
						}
						else {
							$name = join("<BR>", @subjs);	
						}
					}

					my $colspan = "";
					$colspan = qq! colspan="2"! if ($surplus_cols-- > 0);

					#Bold the fixed name events (might be things like 'Lunch')
					if ($machine_day_orgs{$current_org}->{$event}->{"type"} == 1) {
						$content .= qq!<TD${colspan} style="font-weight: bold">$machine_day_orgs{$current_org}->{$event}->{"name"}!;	
					}
					else {
						$content .= qq!<TD${colspan}>$name!;
					}
				}	
				$prev_org = $current_org;
			}

			$content .= qq!</TABLE><br class="new_page">!;
			last if ($teacher_limd);
		}
		$content .=
qq!
</body>
</html>
!;
	}
	else {	
		$post_mode = 0;
	}
}

if (not $post_mode) {
	#user has selected a timetable to download
	if ($download) {
		my $id = undef;
		my $prep_stmt_1 = $con->prepare("SELECT id FROM timetables WHERE is_committed=1 AND published=1 ORDER BY id DESC LIMIT 1");
		if ($prep_stmt_1) {
			my $rc = $prep_stmt_1->execute();
			if ($rc) {
				while (my @rslts = $prep_stmt_1->fetchrow_array()) {
					$id = $rslts[0];
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM timetables", $prep_stmt_1->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM timetables", $prep_stmt_1->errstr, $/;
		}
		
		if (defined $id) {
			print "Status: 302 Moved Temporarily\r\n";
			print "Location: /timetables/$id.xls\r\n";
			print "Content-Type: text/html; charset=UTF-8\r\n";

   			my $res = 
qq{
<html>
<head>
<title>Spanj: Exam Management Information System - Redirect Failed</title>
</head>
<body>
You should have been redirected to <a href="/timetables/$id.xls">/timetables/$id.xls</a>. If you were not, <a href="/timetables/$id.xls">Click here</a> 
</body>
</html>
};

			my $content_len = length($res);	
			print "Content-Length: $content_len\r\n";
			print "\r\n";
			print $res;

			$con->disconnect();
			exit 0;
		}
	}

	else {
		my (@selected_classes,%lesson_to_teachers,%teachers);

		my $prep_stmt_0 = $con->prepare("SELECT selected_classes,lesson_to_teachers,teachers FROM timetables WHERE is_committed=1 AND published=1 ORDER BY id DESC LIMIT 1");

		if ( $prep_stmt_0 ) {
			my $rc = $prep_stmt_0->execute();
			if ($rc) {
				while (my @rslts = $prep_stmt_0->fetchrow_array()) {
					@selected_classes = @{thaw $rslts[0]};
					%lesson_to_teachers = %{thaw $rslts[1]};
					%teachers = %{thaw $rslts[2]};
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM timetables", $prep_stmt_0->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM timetables", $prep_stmt_0->errstr, $/;
		}

		#classes
		my $classes_select = qq!<SELECT name="classes" multiple size="4">!;
		$classes_select .= qq!<OPTION selected value="*">All Classes</OPTION>!;

		for my $class (sort {$a cmp $b} @selected_classes) {
			$classes_select .= qq!<OPTION value="$class">$class</OPTION>!;
		}

		$classes_select .= qq!</SELECT>!;

		#subjects
		my %subjects;

		for my $lesson (keys %lesson_to_teachers) {
			if ($lesson =~ /^([^\(]+)/) {
				my $subject = $1;

				my @edited_subj_bts = ();
				#want to ucfirst() every word in the subject
				my @raw_subj_bts = split/\s+/, $subject;
				for my $raw_subj_bt (@raw_subj_bts) {
					push @edited_subj_bts, ucfirst($raw_subj_bt);
				}
				
				my $edited_subject = join(" ", @edited_subj_bts);
				$subjects{$edited_subject}++;
			}
		}

		my $subjects_select = qq!<SELECT name="subjects" multiple size="4">!;
		$subjects_select .= qq!<OPTION selected value="*">All Subjects</OPTION>!;

		for my $subj (sort {$a cmp $b} keys %subjects) {
			$subjects_select .= qq!<OPTION value="! .lc($subj) . qq!">$subj</OPTION>!;
		}

		$subjects_select .= qq!</SELECT>!;


		#teachers select
		my $teachers_select = qq!<SELECT name="teachers" multiple size="4">!;
		$teachers_select .= qq!<OPTION selected VALUE="*">All Teachers</OPTION>!;

		for my $teacher (sort { $teachers{$a}->{"name"} cmp $teachers{$b}->{"name"} } keys %teachers) {
			$teachers_select .= qq!<OPTION value="$teacher">! .$teachers{$teacher}->{"name"} .qq!</OPTION>!;
		}

		$teachers_select.= qq!</SELECT>!;
		$content = 
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Yans: Timetable Builder - View Timetable</title>
</head>
<BODY>
$header
<p>Would you like to <a href="/cgi-bin/viewtimetable.cgi?act=download">download the entire timetable</a> as a spreadsheet?
<p>Or
<p>View the timetable on your browser?
<p>
<FORM method="POST" action="/cgi-bin/viewtimetable.cgi">
<TABLE>
<TR>
<TD><LABEL for="">Class</LABEL>
<TD>$classes_select
<TD><LABEL for="">Subject</LABEL>
<TD>$subjects_select
<TD><LABEL for="">Teacher</LABEL>
<TD>$teachers_select
<TR>
<TD><INPUT type="submit" name="view" value="View">
</TABLE>
</FORM>
</BODY>
</HTML>
*;
	}
}

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

print "\r\n";
print $content;
$con->disconnect() if (defined $con and $con);

